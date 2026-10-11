"""Stage 4A-3: real HTTP/SQLite concurrency, rollback and task ownership."""
import asyncio
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import Operation, StartDiscussion
from backend.app.main import create_app
from backend.tests.test_lifecycle_api import create, headers
from backend.tests.test_roster_tasks import ScenarioGateway, events, generate, setup, wait_for


def start(client, did, key=None, revision=1):
    response = client.post(f'/api/discussions/{did}/start', json={'roster_revision':revision}, headers=headers(key))
    assert response.status_code == 202, response.text
    return response.json()


def operation(client, did, op_id):
    response = client.get(f'/api/discussions/{did}/operations/{op_id}')
    assert response.status_code == 200, response.text
    return Operation.model_validate(response.json()).model_dump(mode='json')


def ready(client, topic='启动测试', count=None):
    did = create(client, topic, count)['discussion']['id']
    accepted = generate(client, did)
    wait_for(client, did, 'READY')
    return did, accepted


def test_confirm_freezes_roster_and_operation_while_opening_is_in_flight(setup):
    client, gateway = setup()
    did, generation = ready(client)
    accepted = start(client, did)
    snapshot = wait_for(client, did, 'RUNNING')
    assert snapshot['discussion']['run_id'] == accepted['run_id']
    assert len(snapshot['role_states']) == 5
    assert sum(s['state']=='SPEAKING' for s in snapshot['role_states'])<=1
    assert snapshot['messages'] == [] and snapshot['summary'] is None
    assert len(gateway.requests) == 1  # Only roster requests are recorded by this gated fixture.
    assert operation(client,did,generation['operation_id'])['status'] == 'SUCCEEDED'
    op = operation(client,did,accepted['operation_id'])
    assert op == {'id':accepted['operation_id'],'discussion_id':did,'kind':'start','status':'SUCCEEDED','error_code':None}
    with client.app.state.database.connect() as conn:
        run = dict(conn.execute('SELECT * FROM runs WHERE discussion_id=?',(did,)).fetchone())
        assert run['status']=='ACTIVE' and run['roster_revision']==1
        assert (run['max_turns'],run['max_seconds']) == (20,600)
        assert conn.execute('SELECT confirmed_at FROM rosters WHERE discussion_id=?',(did,)).fetchone()[0]
    stream = events(client,did)
    running_events=[e for e in stream if e['type']=='discussion.state_changed' and e['payload']['state']=='RUNNING']
    assert len(running_events)==1 and running_events[0]['run_id']==accepted['run_id']
    assert [e['seq'] for e in stream] == list(range(1,len(stream)+1))
    assert sum(e['payload'].get('state')=='RUNNING' for e in stream)==1
    assert [d['id'] for d in client.get('/api/discussions').json()['items']] == [did]


@pytest.mark.parametrize('state', ['DRAFT','GENERATING','FAILED'])
def test_start_before_roster_confirmation_is_rejected(setup,state):
    client, gateway = setup(ScenarioGateway('failure' if state=='FAILED' else 'valid', gate=state=='GENERATING'))
    did = create(client)['discussion']['id']
    if state != 'DRAFT':
        generate(client,did); wait_for(client,did,state)
    response = client.post(f'/api/discussions/{did}/start', json={'roster_revision':1}, headers=headers())
    assert response.status_code==409 and response.json()['error']['code']=='INVALID_STATE'
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==0


@pytest.mark.parametrize('body',[{}, {'roster_revision':0}, {'roster_revision':True}, {'roster_revision':'1'}, {'roster_revision':1,'extra':1}])
def test_start_request_contract_is_strict(setup,body):
    client,_ = setup()
    did = create(client)['discussion']['id']
    response=client.post(f'/api/discussions/{did}/start',json=body,headers=headers())
    assert response.status_code==422 and response.json()['error']['code']=='VALIDATION_ERROR'


def test_revision_conflict_and_key_conflict_do_not_start_or_change_run(setup):
    client,_ = setup()
    did,_ = ready(client)
    response = client.post(f'/api/discussions/{did}/start',json={'roster_revision':2},headers=headers())
    assert response.status_code==409 and response.json()['error']['code']=='ROSTER_VERSION_CONFLICT'
    assert wait_for(client,did,'READY')['discussion']['run_id'] is None
    key=uuid4(); accepted=start(client,did,key)
    assert start(client,did,key)==accepted
    response=client.post(f'/api/discussions/{did}/start',json={'roster_revision':2},headers=headers(key))
    assert response.status_code==409 and response.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    assert wait_for(client,did,'RUNNING')['discussion']['run_id']==accepted['run_id']


@pytest.mark.parametrize('same_key',[False,True])
def test_concurrent_confirmation_creates_only_one_run_and_transition(setup,same_key):
    client,_ = setup(); did,_ = ready(client)
    key=uuid4(); keys=[key,key if same_key else uuid4()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda value:start(client,did,value),keys))
    assert results[0]==results[1]  # Different keys replay the canonical successful start.
    for key in keys: assert start(client,did,key)==results[0]
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM runs WHERE discussion_id=?',(did,)).fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM role_states WHERE discussion_id=?',(did,)).fetchone()[0]==5
        assert conn.execute("SELECT count(*) FROM operations WHERE discussion_id=? AND kind='start'",(did,)).fetchone()[0]==(1 if same_key else 2)
    assert sum(e['payload'].get('state')=='RUNNING' for e in events(client,did))==1


def test_start_write_failure_rolls_back_run_confirmation_roles_operation_and_event(setup):
    client,_ = setup(); did,_=ready(client); key=uuid4()
    db=client.app.state.database
    with db.connect() as conn:
        conn.execute("CREATE TRIGGER reject_start BEFORE INSERT ON events WHEN json_extract(NEW.payload,'$.state')='RUNNING' BEGIN SELECT RAISE(ABORT,'private-start-sentinel'); END")
    response=client.post(f'/api/discussions/{did}/start',json={'roster_revision':1},headers=headers(key))
    assert response.status_code==503 and 'private-start-sentinel' not in response.text
    snapshot=wait_for(client,did,'READY')
    assert snapshot['discussion']['run_id'] is None and snapshot['last_event_seq']==4
    with db.connect() as conn:
        for table in ('runs','role_states'): assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0
        assert conn.execute("SELECT count(*) FROM operations WHERE kind='start'").fetchone()[0]==0
        assert conn.execute('SELECT confirmed_at FROM rosters').fetchone()[0] is None
        conn.execute('DROP TRIGGER reject_start')
    start(client,did,key); wait_for(client,did,'RUNNING')


def test_capacity_rechecked_at_start_but_duplicate_run_is_allowed_at_capacity(setup):
    client,_=setup(discussion_max_active=1)
    a,_=ready(client,'A'); b,_=ready(client,'B')
    accepted=start(client,a)
    response=client.post(f'/api/discussions/{b}/start',json={'roster_revision':1},headers=headers())
    assert response.status_code==503 and response.json()['error']['code']=='CAPACITY_EXCEEDED'
    assert response.headers['Retry-After']=='2'
    assert start(client,a)==accepted
    assert wait_for(client,b,'READY')['discussion']['run_id'] is None


def test_two_runs_operations_events_and_foreign_keys_remain_scoped(setup):
    client,_=setup(); a,ga=ready(client,'A',2); b,gb=ready(client,'B',6)
    shared_key=uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda did:start(client,did,shared_key),[a,b]))
    assert results[0]['run_id'] != results[1]['run_id']
    for did,other,accepted,gen in [(a,b,results[0],ga),(b,a,results[1],gb)]:
        snapshot=wait_for(client,did,'RUNNING')
        assert {r['participant_id'] for r in snapshot['role_states']}=={p['id'] for p in snapshot['participants']}
        for op_id in [accepted['operation_id'],gen['operation_id']]:
            assert operation(client,did,op_id)['discussion_id']==did
            foreign=client.get(f'/api/discussions/{other}/operations/{op_id}')
            assert foreign.status_code==404 and foreign.json()['error']['code']=='OPERATION_NOT_FOUND'
        assert all(e['run_id'] in (None,accepted['run_id']) for e in events(client,did))
    with client.app.state.database.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('UPDATE discussions SET current_run_id=? WHERE id=?',(results[1]['run_id'],a))
        person=conn.execute('SELECT id FROM participants WHERE discussion_id=?',(b,)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO role_states(discussion_id,run_id,roster_revision,participant_id) VALUES (?,?,1,?)',(a,results[0]['run_id'],person))
        assert not list(conn.execute('PRAGMA foreign_key_check'))


def test_missing_discussion_operation_and_invalid_generation_body(setup):
    client,_=setup(); did=create(client)['discussion']['id']
    assert client.post(f'/api/discussions/{uuid4()}/start',json={'roster_revision':1},headers=headers()).json()['error']['code']=='DISCUSSION_NOT_FOUND'
    assert client.get(f'/api/discussions/{did}/operations/{uuid4()}').json()['error']['code']=='OPERATION_NOT_FOUND'
    assert client.post(f'/api/discussions/{did}/roster-generation',json={'extra':True},headers=headers()).status_code==422


def test_operation_query_exposes_pending_and_sanitized_failed_status(setup):
    client,gateway=setup(ScenarioGateway('failure',gate=True)); did=create(client)['discussion']['id']
    accepted=generate(client,did)
    assert operation(client,did,accepted['operation_id'])['status'] in ('ACCEPTED','RUNNING')
    gateway.release.set(); wait_for(client,did,'FAILED')
    op=operation(client,did,accepted['operation_id'])
    assert op['status']=='FAILED' and op['error_code']=='TASK_FAILED'
    assert 'private-provider-secret-sentinel' not in str(op)


def settings_at(tmp_path):
    return Settings(_env_file=None,database_path=tmp_path/'restart.db',model_provider='mock')


def test_shutdown_interrupts_pending_generation_restart_preserves_topic_and_allows_new_retry(tmp_path):
    settings=settings_at(tmp_path); app=create_app(settings); gateway=ScenarioGateway(gate=True); key=uuid4()
    with TestClient(app) as client:
        app.state.model_gateway=gateway
        did=create(client,'关闭仍保留')['discussion']['id']; accepted=generate(client,did,key)
        wait_for(client,did,'GENERATING')
    assert not app.state.tasks.tasks and gateway.active==0
    with TestClient(create_app(settings)) as client:
        snapshot=wait_for(client,did,'INTERRUPTED')
        assert snapshot['discussion']['failure_stage']=='roster' and snapshot['participants']==[]
        assert snapshot['discussion']['topic']=='关闭仍保留'
        op=operation(client,did,accepted['operation_id'])
        assert op['status']=='INTERRUPTED' and op['error_code']=='SERVICE_INTERRUPTED'
        assert generate(client,did,key)==accepted
        assert not client.app.state.tasks.tasks  # Old key must not resume automatically.
        generate(client,did); assert len(wait_for(client,did,'READY')['participants'])==5


def test_run_shutdown_restart_is_interrupted_and_canonical_start_replays_without_new_run(tmp_path):
    settings=settings_at(tmp_path); key=uuid4()
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=ScenarioGateway()
        did,_=ready(client); accepted=start(client,did,key)
        before=wait_for(client,did,'RUNNING')
    with TestClient(create_app(settings)) as client:
        after=wait_for(client,did,'INTERRUPTED')
        assert after['participants']==before['participants'] and after['messages']==[]
        assert after['discussion']['run_id']==accepted['run_id'] and after['discussion']['failure_stage']=='discussion'
        assert operation(client,did,accepted['operation_id'])['status']=='SUCCEEDED'
        assert start(client,did,key)==accepted and start(client,did)==accepted
        count=after['last_event_seq']
        assert wait_for(client,did,'INTERRUPTED')['last_event_seq']==count
        with client.app.state.database.connect() as conn:
            run=conn.execute('SELECT * FROM runs WHERE discussion_id=?',(did,)).fetchone()
            assert run['status']=='INTERRUPTED' and run['ended_at']
            assert conn.execute('SELECT count(*) FROM runs').fetchone()[0]==1


def test_startup_recovers_stale_task_before_serving_and_recovery_is_idempotent(tmp_path):
    settings=settings_at(tmp_path)
    with TestClient(create_app(settings)) as client:
        did=create(client)['discussion']['id']; repo=client.app.state.repository
    # Commit admission without any in-memory worker: equivalent to a crash after 202.
    accepted,_=repo.admit_generation(UUID(did),uuid4(),3,True)
    request=repo.claim_generation(accepted.body['operation_id'])
    with TestClient(create_app(settings)) as client:
        snapshot=wait_for(client,did,'INTERRUPTED'); count=snapshot['last_event_seq']
        assert operation(client,did,accepted.body['operation_id'])['status']=='INTERRUPTED'
        assert not client.app.state.tasks.tasks
        assert client.app.state.repository.recover_unfinished()==0
        assert client.get(f'/api/discussions/{did}').json()['last_event_seq']==count
        # Delayed result from the old operation must not overwrite the new attempt.
        gateway=ScenarioGateway(gate=True); client.app.state.model_gateway=gateway
        generate(client,did)
        raw=asyncio.run(ScenarioGateway().generate(request))
        assert client.app.state.repository.complete_generation(accepted.body['operation_id'],request,raw) is False
        assert wait_for(client,did,'GENERATING')['participants']==[]
        gateway.release.set(); wait_for(client,did,'READY')


def test_shutdown_waits_for_sqlite_commit_in_flight_to_prevent_late_writes(tmp_path,monkeypatch):
    app=create_app(settings_at(tmp_path)); entered=threading.Event(); release=threading.Event(); completed=threading.Event()
    context=TestClient(app); client=context.__enter__(); repository=app.state.repository
    original=repository.complete_generation
    def controlled(*args):
        entered.set(); assert release.wait(3)
        result=original(*args); completed.set(); return result
    monkeypatch.setattr(repository,'complete_generation',controlled)
    did=create(client)['discussion']['id']; generate(client,did)
    assert entered.wait(3)
    timer=threading.Timer(.15,release.set); timer.start()
    try:
        context.__exit__(None,None,None)
        assert completed.is_set(), 'shutdown returned before the SQLite worker completed'
    finally:
        release.set(); timer.join(); completed.wait(3)
    with TestClient(create_app(settings_at(tmp_path))) as restarted:
        assert len(wait_for(restarted,did,'READY')['participants'])==5


def test_callback_cannot_write_a_foreign_operation_and_failure_does_not_affect_other_discussion(setup):
    client,gateway=setup(ScenarioGateway(gate=True))
    a=create(client,'A')['discussion']['id']; b=create(client,'B')['discussion']['id']
    ga=generate(client,a); gb=generate(client,b)
    end=time.monotonic()+3
    while len(gateway.requests)<2 and time.monotonic()<end: time.sleep(.005)
    req=next(r for r in gateway.requests if str(r.discussion_id)==a)
    result=asyncio.run(ScenarioGateway().generate(req))
    assert client.app.state.repository.complete_generation(gb['operation_id'],req,result) is False
    assert client.app.state.repository.fail_generation(ga['operation_id'],'TASK_FAILED','嘉宾任务失败，可以重试。')
    gateway.release.set()
    assert wait_for(client,a,'FAILED')['participants']==[]
    assert len(wait_for(client,b,'READY')['participants'])==5
    assert operation(client,a,ga['operation_id'])['status']=='FAILED'
    assert operation(client,b,gb['operation_id'])['status']=='SUCCEEDED'


def test_shutting_down_service_rejects_new_admission_without_writes(setup):
    client,_=setup(); did=create(client)['discussion']['id']
    client.app.state.tasks.closing=True
    response=client.post(f'/api/discussions/{did}/roster-generation',headers=headers())
    assert response.status_code==503 and response.json()['error']['code']=='SERVICE_SHUTTING_DOWN'
    assert wait_for(client,did,'DRAFT')['last_event_seq']==1
