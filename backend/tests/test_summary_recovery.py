"""4C-3 real HTTP retry, concurrency, interruption and discussion isolation."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID,uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.synthesis_repository import SynthesisClaim
from backend.tests.test_lifecycle_api import headers
from backend.tests.test_start_recovery import operation, start
from backend.tests.test_discussion_engine import start_ready
from backend.tests.test_insight_pipeline import synthesis_client, wait_projection, evidence
from backend.tests.test_roster_tasks import events,wait_for
from backend.tests.test_summary_pipeline import FinalGateway


def retry(client,did,key=None):
    response=client.post(f'/api/discussions/{did}/summary-retry',headers=headers(key),json={})
    assert response.status_code==202,response.text
    return response.json()


class RecoveryGateway(FinalGateway):
    def __init__(self,mode='invalid'):
        super().__init__(summary_mode=mode)
        self.hold_summary=False; self.summary_entered=threading.Event()

    async def generate(self,request):
        if request.task=='summary':
            self.summary_entered.set()
            while self.hold_summary: await asyncio.sleep(.005)
        return await super().generate(request)


@pytest.mark.parametrize('mode',['invalid','timeout','exception'])
def test_failed_summary_retries_original_run_without_replaying_discussion(synthesis_client,mode):
    client,gateway=synthesis_client(RecoveryGateway(mode),summary_max_seconds=3)
    did,started=start_ready(client)
    failed=wait_for(client,did,'FAILED')
    before=[r for r in gateway.requests if r.task in ('utterance','intent','host_control')]
    gateway.summary_mode='valid'
    key=uuid4(); accepted=retry(client,did,key)
    completed=wait_for(client,did,'COMPLETED')
    assert completed['messages']==failed['messages'] and completed['insights']==failed['insights']
    assert completed['participants']==failed['participants']
    assert accepted['run_id']==started['run_id']
    assert operation(client,did,accepted['operation_id'])['status']=='SUCCEEDED'
    assert retry(client,did,key)==accepted
    assert before==[r for r in gateway.requests if r.task in ('utterance','intent','host_control')]
    assert len(gateway.summary_calls)==3
    assert start(client,did)==started
    assert sum(e['type']=='summary.ready' for e in events(client,did))==1


def test_duplicate_and_concurrent_retry_keys_share_one_pending_job_and_task(synthesis_client):
    client,gateway=synthesis_client(RecoveryGateway(),model_timeout_seconds=5)
    did,_=start_ready(client); wait_for(client,did,'FAILED')
    gateway.summary_mode='valid'; gateway.hold_summary=True; gateway.summary_entered.clear()
    same=uuid4(); keys=[same,same,uuid4(),uuid4()]
    with ThreadPoolExecutor(max_workers=4) as pool: accepted=list(pool.map(lambda key:retry(client,did,key),keys))
    assert all(a==accepted[0] for a in accepted)
    assert gateway.summary_entered.wait(1)
    assert len(client.app.state.tasks.summary_tasks)==1
    with client.app.state.database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM summary_jobs WHERE status='PENDING'").fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM summary_jobs').fetchone()[0]==2
    gateway.hold_summary=False
    completed=wait_for(client,did,'COMPLETED')
    assert len(gateway.summary_calls)==3
    assert sum(e['type']=='summary.ready' for e in events(client,did))==1
    assert completed['summary']['through_turn']==7


def test_old_failed_summary_result_cannot_overwrite_retry_or_completed_result(synthesis_client):
    client,gateway=synthesis_client(RecoveryGateway(),model_timeout_seconds=5)
    did,_=start_ready(client); wait_for(client,did,'FAILED')
    with client.app.state.database.connect() as conn: old=conn.execute('SELECT id FROM summary_jobs').fetchone()['id']
    claim=SynthesisClaim(UUID(old),gateway.summary_calls[0])
    gateway.summary_mode='valid'; gateway.hold_summary=True
    retry(client,did)
    repo=client.app.state.repository
    assert repo.complete_summary(claim,{'task':'summary','content':'旧结果覆盖'}) is False
    gateway.hold_summary=False; before=wait_for(client,did,'COMPLETED')
    assert repo.complete_summary(claim,{'task':'summary','content':'完成后覆盖'}) is False
    assert client.get(f'/api/discussions/{did}').json()==before


@pytest.mark.parametrize('location',['summary_event','completed_event'])
def test_automatic_summary_write_failure_then_retry_succeeds_without_partial_success(synthesis_client,location):
    gateway=RecoveryGateway('valid'); gateway.release.clear()
    client,gateway=synthesis_client(gateway)
    did,_=start_ready(client)
    condition="NEW.type='summary.ready'" if location=='summary_event' else "NEW.type='discussion.state_changed' AND json_extract(NEW.payload,'$.state')='COMPLETED'"
    with client.app.state.database.connect() as conn:
        conn.execute(f"CREATE TRIGGER break_final BEFORE INSERT ON events WHEN {condition} BEGIN SELECT RAISE(ABORT,'test failure'); END")
    gateway.release.set(); failed=wait_for(client,did,'FAILED')
    assert failed['summary'] is None and failed['discussion']['failure_code']=='DATABASE_UNAVAILABLE'
    assert failed['discussion']['failure_stage']=='summary'
    assert not any(e['type']=='summary.ready' for e in events(client,did))
    with client.app.state.database.connect() as conn: conn.execute('DROP TRIGGER break_final')
    retry(client,did); completed=wait_for(client,did,'COMPLETED')
    assert completed['messages']==failed['messages'] and completed['insights']==failed['insights']
    assert sum(e['type']=='summary.ready' for e in events(client,did))==1


def test_shutdown_restart_preserves_messages_and_insights_and_allows_summary_only_retry(tmp_path):
    settings=Settings(_env_file=None,database_path=tmp_path/'restart.sqlite3',discussion_max_turns=7,model_timeout_seconds=5)
    gateway=RecoveryGateway('valid'); gateway.hold_summary=True
    app=create_app(settings)
    with TestClient(app) as client:
        app.state.model_gateway=gateway; gateway.repository=app.state.repository
        did,started=start_ready(client)
        before=wait_projection(client,did,lambda s:s['discussion']['state']=='SUMMARIZING' and s['insights']['through_turn']==7)
        assert gateway.summary_entered.wait(1)
    assert not app.state.tasks.run_tasks and not app.state.tasks.summary_tasks
    with TestClient(create_app(settings)) as client:
        after=wait_for(client,did,'INTERRUPTED')
        assert after['discussion']['failure_stage']=='summary'
        assert after['messages']==before['messages'] and after['insights']==before['insights']
        fresh=RecoveryGateway('valid'); fresh.repository=client.app.state.repository; client.app.state.model_gateway=fresh
        retry(client,did); done=wait_for(client,did,'COMPLETED')
        assert done['discussion']['run_id']==started['run_id']
        assert done['messages']==before['messages'] and done['participants']==before['participants']
        assert len(fresh.summary_calls)==1 and fresh.requests==[]


def test_two_discussions_overlap_and_failure_and_retry_are_isolated(synthesis_client):
    class SplitGateway(RecoveryGateway):
        async def generate(self,request):
            if request.task=='insights':
                self.requests.append(request)
                return evidence(request)
            if request.task=='summary':
                self.summary_calls.append(request)
                while self.hold_summary: await asyncio.sleep(.005)
                if request.topic=='A' and self.summary_mode=='invalid': return {'task':'summary','content':'{}'}
                return {'task':'summary','content':f'本场{request.topic}总结：先试点，成本边界未解决。'}
            return await super().generate(request)
    gateway=SplitGateway(); gateway.release.clear(); gateway.hold_summary=True
    client,gateway=synthesis_client(gateway,model_timeout_seconds=5)
    a,_=start_ready(client,'A'); b,_=start_ready(client,'B')
    gateway.release.set()
    wait_projection(client,a,lambda s:s['insights']['through_turn']==7)
    wait_projection(client,b,lambda s:s['insights']['through_turn']==7)
    end=time.monotonic()+2
    while len({r.discussion_id for r in gateway.summary_calls})<2 and time.monotonic()<end: time.sleep(.005)
    assert len({r.discussion_id for r in gateway.summary_calls})==2
    gateway.hold_summary=False
    failed=wait_for(client,a,'FAILED'); complete_b=wait_for(client,b,'COMPLETED')
    gateway.summary_mode='valid'; retry(client,a); complete_a=wait_for(client,a,'COMPLETED')
    assert client.get(f'/api/discussions/{b}').json()==complete_b
    assert complete_a['messages']==failed['messages']
    for did,snapshot in [(a,complete_a),(b,complete_b)]:
        sources={m['id'] for m in snapshot['messages']}
        assert all(set(i['source_message_ids'])<=sources for i in snapshot['insights']['items'])
        assert all(e['discussion_id']==did for e in events(client,did))
        assert did in snapshot['summary']['content'] or ('A' if did==a else 'B') in snapshot['summary']['content']


def test_retry_rejects_wrong_state_foreign_id_bad_body_and_completed_new_key(synthesis_client):
    gateway=RecoveryGateway('valid'); gateway.hold_summary=True
    client,gateway=synthesis_client(gateway,model_timeout_seconds=5)
    did,_=start_ready(client); wait_for(client,did,'SUMMARIZING')
    assert client.post(f'/api/discussions/{did}/summary-retry',headers=headers(),json={}).status_code==409
    assert client.post(f'/api/discussions/{uuid4()}/summary-retry',headers=headers(),json={}).status_code==404
    assert client.post(f'/api/discussions/{did}/summary-retry',headers=headers(),json={'run_id':str(uuid4())}).status_code==422
    gateway.hold_summary=False; wait_for(client,did,'COMPLETED')
    assert client.post(f'/api/discussions/{did}/summary-retry',headers=headers(),json={}).status_code==409


def test_summary_returning_after_cancellation_cannot_commit_and_can_be_retried(synthesis_client):
    class SwallowGateway(RecoveryGateway):
        async def generate(self,request):
            if request.task=='summary' and self.summary_mode=='late':
                self.summary_calls.append(request)
                try: await asyncio.sleep(3)
                except asyncio.CancelledError: pass
                return {'task':'summary','content':'预算后迟到结果。'}
            return await super().generate(request)
    client,gateway=synthesis_client(SwallowGateway('late'),summary_max_seconds=1,model_timeout_seconds=5)
    did,_=start_ready(client); failed=wait_for(client,did,'FAILED')
    assert failed['discussion']['failure_code']=='MODEL_TIMEOUT' and failed['summary'] is None
    assert len(gateway.summary_calls)==1
    gateway.summary_mode='valid'; retry(client,did)
    completed=wait_for(client,did,'COMPLETED')
    assert completed['summary']['content']!='预算后迟到结果。'


def test_retry_admission_write_failure_rolls_back_run_state_operation_and_job(synthesis_client):
    client,gateway=synthesis_client(RecoveryGateway())
    did,_=start_ready(client); before=wait_for(client,did,'FAILED')
    with client.app.state.database.connect() as conn:
        initial=conn.execute('SELECT count(*) FROM operations').fetchone()[0]
        conn.execute("CREATE TRIGGER fail_retry BEFORE INSERT ON summary_jobs WHEN NEW.operation_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'test retry admission'); END")
    gateway.summary_mode='valid'; key=uuid4()
    response=client.post(f'/api/discussions/{did}/summary-retry',headers=headers(key),json={})
    assert response.status_code==503
    assert client.get(f'/api/discussions/{did}').json()==before
    assert not client.app.state.tasks.summary_tasks
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM operations').fetchone()[0]==initial
        assert conn.execute('SELECT count(*) FROM summary_jobs').fetchone()[0]==1
        assert conn.execute('SELECT status FROM runs').fetchone()[0]=='FAILED'
        conn.execute('DROP TRIGGER fail_retry')
    retry(client,did,key); wait_for(client,did,'COMPLETED')


def test_service_shutdown_rejects_provider_that_swallows_task_cancellation(tmp_path):
    class SwallowShutdown(RecoveryGateway):
        async def generate(self,request):
            if request.task=='summary':
                self.summary_entered.set()
                try: await asyncio.sleep(20)
                except asyncio.CancelledError: pass
                return {'task':'summary','content':'服务关闭后迟到总结。'}
            return await super().generate(request)
    settings=Settings(_env_file=None,database_path=tmp_path/'cancel.sqlite3',discussion_max_turns=7)
    app=create_app(settings); gateway=SwallowShutdown('valid')
    with TestClient(app) as client:
        gateway.repository=app.state.repository; app.state.model_gateway=gateway
        did,_=start_ready(client); assert gateway.summary_entered.wait(2)
    snapshot=app.state.repository.snapshot(UUID(did))
    assert snapshot.discussion.state=='INTERRUPTED'
    assert snapshot.discussion.failure_stage=='summary' and snapshot.summary is None


def test_discussion_stage_failure_cannot_be_retried_as_summary(synthesis_client):
    gateway=RecoveryGateway(); gateway.mode='long'
    client,gateway=synthesis_client(gateway)
    did,_=start_ready(client); failed=wait_for(client,did,'FAILED')
    assert failed['discussion']['failure_stage']=='discussion'
    response=client.post(f'/api/discussions/{did}/summary-retry',json={},headers=headers())
    assert response.status_code==409 and response.json()['error']['code']=='INVALID_STATE'
    assert client.get(f'/api/discussions/{did}').json()==failed
