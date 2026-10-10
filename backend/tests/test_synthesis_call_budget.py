"""Multi-request synthesis has one finite task deadline and per-HTTP timeouts."""
import asyncio,time,json
from types import SimpleNamespace
import httpx,pytest
from backend.app.deepseek_gateway import DeepSeekGateway
from backend.app.engine import DiscussionEngine,RunDeadline
from backend.tests.test_deepseek import config,request,answer


def test_valid_subcalls_can_exceed_single_http_timeout_in_total():
    model_request=request('insights')
    async def run():
        seen=[]
        async def upstream(req):
            assert req.extensions['timeout']['read']==1
            await asyncio.sleep(.65)
            context=json.loads(json.loads(req.content)['messages'][1]['content']);seen.append(context)
            return httpx.Response(200,json=answer({'reviews':[]} if 'candidate' in context else {'items':[]}))
        settings=config(model_timeout_seconds=1,model_max_attempts=2)
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(settings,client)
            supervisor=SimpleNamespace(repository=None,_db_call=None,settings=settings,gateway_getter=lambda:gateway,semaphore=asyncio.Semaphore(1),closing=False)
            engine=DiscussionEngine(supervisor);engine.deadline=time.monotonic()+3
            result=await engine.call_model(model_request)
            assert result.items==() and len(seen)==2
            assert all(m['status']=='succeeded' for m in gateway.metrics)
    asyncio.run(run())


def test_real_http_still_times_out_per_request_and_has_finite_retries():
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from backend.app.engine import ModelCallFailure
    seen=[]
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']));seen.append(1)
            time.sleep(1.3)
            payload=json.dumps(answer({'items':[]})).encode()
            try:
                self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    model_request=request('insights')
    async def run():
        settings=config(model_timeout_seconds=1)
        settings.model_base_url=f'http://127.0.0.1:{server.server_port}'
        gateway=DeepSeekGateway(settings)
        supervisor=SimpleNamespace(repository=None,_db_call=None,settings=settings,gateway_getter=lambda:gateway,semaphore=asyncio.Semaphore(1),closing=False)
        engine=DiscussionEngine(supervisor);engine.deadline=time.monotonic()+5
        try:
            with pytest.raises(ModelCallFailure) as error:await engine.call_model(model_request)
            assert error.value.code=='MODEL_TIMEOUT' and len(seen)==2
            assert all(m['status']=='MODEL_TIMEOUT' for m in gateway.metrics)
        finally:await gateway.aclose()
    try:asyncio.run(run())
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def test_task_deadline_still_cancels_inflight_synthesis():
    model_request=request('insights')
    async def run():
        async def upstream(_):
            await asyncio.sleep(10)
        settings=config(model_timeout_seconds=1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(settings,client)
            supervisor=SimpleNamespace(repository=None,_db_call=None,settings=settings,gateway_getter=lambda:gateway,semaphore=asyncio.Semaphore(1),closing=False)
            engine=DiscussionEngine(supervisor);engine.deadline=time.monotonic()+.1
            with pytest.raises(RunDeadline):await engine.call_model(model_request)
            assert len(gateway.metrics)==1 and gateway.metrics[0]['status']=='cancelled'
    asyncio.run(run())
