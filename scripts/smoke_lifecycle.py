"""Owned local server processes + real HTTP/SQLite; mock provider, no frontend."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from backend.app.contracts import EventAdapter, Operation, OperationAccepted, Snapshot
from backend.app.database import Database

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT/'work').mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='lifecycle-smoke-', dir=ROOT/'work')).resolve()
    assert workspace.is_relative_to((ROOT/'work').resolve())
    db_path = workspace/'panel.sqlite3'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    report = {'mode':'real FastAPI/SQLite/HTTP + deterministic backend mock','checks':[]}

    def http(method,path,body=None,key=None,expected=200):
        headers = {'Content-Type':'application/json'}
        if key: headers['Idempotency-Key']=str(key)
        request = Request(origin+path, data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None, headers=headers,method=method)
        try:
            response = urlopen(request,timeout=5)
        except HTTPError as error:
            response = error
        with response:
            value=json.load(response)
            assert response.status==expected, (path,response.status,value)
        return value

    def poll(did,state):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            snapshot=Snapshot.model_validate(http('GET',f'/api/discussions/{did}')).model_dump(mode='json')
            if snapshot['discussion']['state']==state: return snapshot
            time.sleep(.02)
        raise AssertionError(f'Expected {state}, last={snapshot}')

    processes, logs = [], []
    def launch():
        log=(workspace/f'server-{len(processes)+1}.log').open('w',encoding='utf-8')
        logs.append(log)
        environment = os.environ | {'BACKEND_HOST':'127.0.0.1','BACKEND_PORT':str(port),'DATABASE_PATH':str(db_path),'MODEL_PROVIDER':'mock','MODEL_TIMEOUT_SECONDS':'30','MODEL_MAX_CONCURRENCY':'4','DISCUSSION_MAX_ACTIVE':'3','PYTHONUTF8':'1'}
        process = subprocess.Popen([sys.executable,'-m','backend.app.server'],cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        processes.append(process)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            assert process.poll() is None, 'Owned server failed; inspect local log'
            try:
                if http('GET','/api/health/ready')['status']=='ready': return process
            except (URLError,TimeoutError,ConnectionError):
                pass
            time.sleep(.05)
        raise AssertionError('Server startup timed out')

    try:
        first=launch()
        assert http('GET','/api/system')['phase']==4
        invalid=http('POST','/api/discussions',{'topic':' ','expert_count':1},uuid4(),422)
        assert invalid['error']['code']=='VALIDATION_ERROR'
        a=Snapshot.model_validate(http('POST','/api/discussions',{'topic':'默认人数持久化检查'},uuid4(),201)).model_dump(mode='json')
        b=Snapshot.model_validate(http('POST','/api/discussions',{'topic':'另一场六专家讨论','expert_count':6},uuid4(),201)).model_dump(mode='json')
        draft=http('POST','/api/discussions',{'topic':'重启保留草稿'},uuid4(),201)
        dids=[s['discussion']['id'] for s in [a,b]]
        generation_keys=[uuid4(),uuid4()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            generated=list(pool.map(lambda pair:OperationAccepted.model_validate(http('POST',f'/api/discussions/{pair[0]}/roster-generation',{},pair[1],202)).model_dump(mode='json'),zip(dids,generation_keys)))
        snapshots=[poll(did,'READY') for did in dids]
        assert [len(s['participants']) for s in snapshots]==[5,7]
        report['checks'].append('Two topics generated through independent backend gateway; default 4 and explicit 6 experts persisted')
        path=f'/api/discussions/{dids[0]}/start'
        with ThreadPoolExecutor(max_workers=2) as pool:
            started=list(pool.map(lambda key:http('POST',path,{'roster_revision':1},key,202),[uuid4(),uuid4()]))
        assert started[0]==started[1]
        other=http('POST',f'/api/discussions/{dids[1]}/start',{'roster_revision':1},uuid4(),202)
        running=[poll(did,'SUMMARIZING') for did in dids]
        for snapshot in running:
            assert len(snapshot['messages'])==8 and snapshot['messages'][0]['kind']=='opening'
            assert [m['turn_no'] for m in snapshot['messages']]==list(range(1,9))
            assert snapshot['summary'] is None and snapshot['insights']['items']==[]
        assert started[0]['run_id']!=other['run_id']
        for did,accepted in zip(dids,generated):
            assert Operation.model_validate(http('GET',f"/api/discussions/{did}/operations/{accepted['operation_id']}" )).status=='SUCCEEDED'
        foreign=http('GET',f"/api/discussions/{dids[1]}/operations/{started[0]['operation_id']}",expected=404)
        assert foreign['error']['code']=='OPERATION_NOT_FOUND'
        assert len(http('GET','/api/discussions')['items'])==2
        report['checks'].append('Concurrent confirmation returned one canonical run; two isolated runs automatically committed 8 messages each and stopped at SUMMARIZING through host control')
        report['before_restart']=running
        # Terminate only the process owned by this script: exercise abrupt restart, not graceful close.
        first.terminate(); first.wait(timeout=10)
        launch()
        recovered=[poll(did,'INTERRUPTED') for did in dids]
        assert [s['participants'] for s in recovered]==[s['participants'] for s in running]
        assert all(s['discussion']['failure_stage']=='summary' for s in recovered)
        assert [s['messages'] for s in recovered]==[s['messages'] for s in running]
        assert poll(draft['discussion']['id'],'DRAFT')['discussion']['topic']=='重启保留草稿'
        assert http('POST',path,{'roster_revision':1},uuid4(),202)==started[0]
        assert http('POST',f'/api/discussions/{dids[0]}/roster-generation',{},generation_keys[0],202)==generated[0]
        assert http('GET','/api/discussions')['items']==[]
        report['checks'].append('Abrupt restart preserved 16 messages and rosters; pending summaries became INTERRUPTED/summary; old commands did not create/resume a run')
        report['after_restart']=recovered
        database=Database(db_path)
        with database.connect(create=False) as conn:
            assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==2
            assert not list(conn.execute('PRAGMA foreign_key_check'))
            stream=[dict(r) for r in conn.execute('SELECT * FROM events ORDER BY discussion_id,seq')]
        for event in stream:
            event['payload']=json.loads(event['payload'])
            EventAdapter.validate_python(event)
        for snapshot in recovered:
            events=[e for e in stream if e['discussion_id']==snapshot['discussion']['id']]
            assert [e['seq'] for e in events]==list(range(1,snapshot['last_event_seq']+1))
        report['events']=stream
        report['checks'].append('SQLite foreign key check clean; append-only persisted events validated with contiguous per-discussion sequence')
        destination=workspace/'report.json'
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'Lifecycle HTTP smoke passed: {destination}')
        for check in report['checks']: print(check)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate(); process.wait(timeout=10)
        for log in logs: log.close()


if __name__=='__main__':
    main()
