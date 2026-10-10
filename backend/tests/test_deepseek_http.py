"""Actual loopback HTTP upstream, actual FastAPI task lifecycle and temporary SQLite."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_lifecycle_api import create
from backend.tests.test_roster_tasks import generate, wait_for, events
from backend.tests.test_start_recovery import start


def test_all_six_tasks_over_actual_http_with_safe_public_responses(tmp_path):
    calls=[]
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            assert self.path=='/v1/chat/completions'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context=json.loads(body['messages'][1]['content'])
            task=context['task']
            calls.append((task,context))
            if task=='roster': output={'participants':[{'kind':'HOST' if i==0 else 'EXPERT','name':f'嘉宾{i}','title':f'职业{i}','stance':f'视角{i}'} for i in range(context['expert_count']+1)]}
            elif task=='intent': output={'kind':'REBUT','target_turn':1,'relevance':80,'public_focus':'执行成本'}
            elif task=='utterance': output={'sentences':['应限定范围并明确执行成本。']}
            elif task=='host_control': output={'action':'end' if len(context['messages'])>=4 else 'followup','public_focus':'请回应成本边界'}
            elif task=='insights': output={'reviews':[]} if 'candidate' in context else {'items':[]}
            else: output={'introduction':'本场比较执行成本。','positions':[],'consensus_indices':[],'disagreement_indices':[],'pending':[]} if 'candidate' in context else {'content':'主持人总结：各方讨论了执行成本，但尚未充分形成共识。'}
            payload=json.dumps({'model':'controlled-http','choices':[{'finish_reason':'stop','message':{'content':json.dumps(output,ensure_ascii=False),'reasoning_content':'hidden-provider-sentinel'}}],'usage':{'total_tokens':15}}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        settings=Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_provider='deepseek',model_base_url=f'http://127.0.0.1:{server.server_port}/v1',model_name='controlled-http',model_api_key='http-secret-sentinel')
        app=create_app(settings)
        with TestClient(app) as client:
            assert client.get('/api/health/ready').json()['model_mode']=='real'
            did=create(client,'课堂手机是否应有条件使用')['discussion']['id']
            generate(client,did);wait_for(client,did,'READY');start(client,did)
            snapshot=wait_for(client,did,'COMPLETED',timeout=10)
            assert len(snapshot['messages'])==4 and snapshot['summary']['through_turn']==4
            assert {task for task,_ in calls}=={'roster','intent','utterance','host_control','insights','summary'}
            public=json.dumps(snapshot)+json.dumps(events(client,did))+client.get('/api/system').text
            assert 'hidden-provider-sentinel' not in public and 'http-secret-sentinel' not in public
            assert all(x['status']=='succeeded' for x in app.state.model_gateway.metrics)
            assert app.state.database.ready()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
