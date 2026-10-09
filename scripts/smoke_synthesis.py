"""Real loopback HTTP/SQLite with controlled backend faults; no UI fixture data."""
import asyncio
import json
import socket
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from uuid import uuid4

import uvicorn

from backend.app.config import Settings
from backend.app.contracts import EventAdapter,Snapshot
from backend.app.database import Database
from backend.app.main import create_app
from backend.app.model_gateway import DeterministicModelGateway

ROOT=Path(__file__).resolve().parents[1]


class FaultGateway(DeterministicModelGateway):
    def __init__(self, repaired=False):
        self.repaired=repaired
        self.summary_calls=Counter()
        self.hold=threading.Event()
        self.hold.set()

    async def generate(self,request):
        if request.task=='summary':
            self.summary_calls[str(request.discussion_id)]+=1
            while not self.hold.is_set(): await asyncio.sleep(.005)
            if request.topic=='A：总结恢复检查' and not self.repaired:
                return {'task':'summary','content':'{"raw":"invalid JSON body"}'}
        return await super().generate(request)


def main():
    (ROOT/'work').mkdir(exist_ok=True)
    workspace=Path(tempfile.mkdtemp(prefix='synthesis-smoke-',dir=ROOT/'work')).resolve()
    assert workspace.is_relative_to((ROOT/'work').resolve())
    settings=Settings(_env_file=None,database_path=workspace/'panel.sqlite3',model_timeout_seconds=5,summary_max_seconds=15)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    owned=[]

    def http(method,path,body=None,key=None,expected=200):
        headers={'Content-Type':'application/json'}
        if key: headers['Idempotency-Key']=str(key)
        req=Request(origin+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=headers,method=method)
        try: response=urlopen(req,timeout=5)
        except HTTPError as error: response=error
        with response:
            value=json.load(response)
            assert response.status==expected,(path,response.status,value)
            return value

    def poll(did,state):
        end=time.monotonic()+10
        while time.monotonic()<end:
            snapshot=Snapshot.model_validate(http('GET',f'/api/discussions/{did}')).model_dump(mode='json')
            if snapshot['discussion']['state']==state: return snapshot
            time.sleep(.01)
        raise AssertionError(f'Expected {state}: {snapshot}')

    def launch(gateway):
        app=create_app(settings); original=app.router.lifespan_context
        @asynccontextmanager
        async def lifespan(current):
            async with original(current):
                current.state.model_gateway=gateway
                yield
        app.router.lifespan_context=lifespan
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
        thread=threading.Thread(target=server.run,name='owned-synthesis-http',daemon=True)
        owned.append((server,thread,gateway)); thread.start()
        end=time.monotonic()+10
        while time.monotonic()<end:
            try:
                if http('GET','/api/health/ready')['status']=='ready': return app,server,thread
            except (URLError,TimeoutError,ConnectionError): pass
            time.sleep(.02)
        raise AssertionError('Owned server startup failed')

    def stop(server,thread):
        server.should_exit=True; thread.join(timeout=10)
        assert not thread.is_alive(),'Owned server failed to stop'

    report={'mode':'real TCP HTTP / FastAPI / SQLite with deterministic controlled backend gateway','checks':[]}
    try:
        gateway=FaultGateway(); app,server,thread=launch(gateway)
        dids=[]
        for topic in ['A：总结恢复检查','B：正常完成检查']:
            created=http('POST','/api/discussions',{'topic':topic},uuid4(),201)
            did=created['discussion']['id']; dids.append(did)
            http('POST',f'/api/discussions/{did}/roster-generation',{},uuid4(),202); poll(did,'READY')
        with ThreadPoolExecutor(max_workers=2) as pool:
            started=list(pool.map(lambda did:http('POST',f'/api/discussions/{did}/start',{'roster_revision':1},uuid4(),202),dids))
        a,b=dids
        failed=poll(a,'FAILED'); done_b=poll(b,'COMPLETED')
        assert failed['discussion']['failure_stage']=='summary' and gateway.summary_calls[a]==2
        assert len(failed['messages'])==len(done_b['messages'])==8
        gateway.repaired=True; gateway.hold.clear()
        keys=[uuid4(),uuid4()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            retried=list(pool.map(lambda key:http('POST',f'/api/discussions/{a}/summary-retry',{},key,202),keys))
        assert retried[0]==retried[1]
        assert len(app.state.tasks.summary_tasks)==1
        stop(server,thread)
        fresh=FaultGateway(repaired=True); app,server,thread=launch(fresh)
        interrupted=poll(a,'INTERRUPTED')
        assert interrupted['discussion']['failure_stage']=='summary'
        assert interrupted['messages']==failed['messages'] and interrupted['insights']==failed['insights']
        assert http('POST',f'/api/discussions/{a}/summary-retry',{},keys[0],202)==retried[0]
        assert not app.state.tasks.summary_tasks and fresh.summary_calls[a]==0
        accepted=http('POST',f'/api/discussions/{a}/summary-retry',{},uuid4(),202)
        done_a=poll(a,'COMPLETED')
        assert accepted['run_id']==started[0]['run_id'] and done_a['messages']==failed['messages']
        assert done_a['insights']==failed['insights'] and done_a['participants']==failed['participants']
        assert fresh.summary_calls[a]==1
        assert poll(b,'COMPLETED')==done_b
        database=Database(settings.database_path)
        with database.connect(create=False) as conn:
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
            assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==2
            assert conn.execute('SELECT count(*) FROM messages').fetchone()[0]==16
            stream=[dict(row) for row in conn.execute('SELECT * FROM events ORDER BY discussion_id,seq')]
            report['summary_jobs']=[dict(row) for row in conn.execute('SELECT * FROM summary_jobs ORDER BY discussion_id,attempt')]
        for event in stream:
            event['payload']=json.loads(event['payload']); EventAdapter.validate_python(event)
        for did in dids:
            scoped=[e for e in stream if e['discussion_id']==did]
            assert [e['seq'] for e in scoped]==list(range(1,len(scoped)+1))
            assert sum(e['type']=='summary.ready' for e in scoped)==1
            state='DRAFT'; live=[]
            for event in scoped:
                if event['type']=='discussion.state_changed': state=event['payload']['state']
                if event['type']=='insights.updated' and event['payload']['items'] and state=='RUNNING': live.append(event['payload']['through_turn'])
            assert len(live)>=2
            report.setdefault('live_insight_boundaries',{})[did]=live
        report['checks']=['Two independent runs each committed 8 messages; nonempty evidence updated at least twice before discussion ended',
                          'A exhausted two invalid summary attempts; B completed unaffected',
                          'Concurrent retry keys joined one pending task; shutdown interrupted it',
                          'Restart retained all messages and evidence; old key did not resume; new key completed same run and boundary',
                          'One summary.ready per run; per-discussion event order contiguous; SQLite foreign keys clean']
        report['events']=stream; report['completed']=[done_a,done_b]
        destination=workspace/'report.json'; destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'Synthesis HTTP smoke passed: {destination}')
        for check in report['checks']: print(check)
    finally:
        for server,thread,gateway in owned:
            gateway.hold.set()
            if thread.is_alive(): stop(server,thread)


if __name__=='__main__': main()
