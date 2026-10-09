"""4B-3 real FastAPI/SQLite automatic progression using controlled backend models."""
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.model_gateway import DeterministicModelGateway
from backend.tests.test_lifecycle_api import create,headers
from backend.tests.test_roster_tasks import generate,wait_for,events
from backend.tests.test_start_recovery import start


class ControlledGateway(DeterministicModelGateway):
    def __init__(self,mode='REQUEST',gate=False):
        self.mode=mode; self.requests=[]; self.release=threading.Event()
        if not gate: self.release.set()
        self.repository=None
        self.active=0

    async def generate(self,request):
        if request.task=='roster': return await super().generate(request)
        self.requests.append(request); self.active+=1
        try:
            if request.task=='utterance' and request.host_task=='opening':
                while not self.release.is_set(): await asyncio.sleep(.005)
            await asyncio.sleep(.003)
            if self.mode=='fail_A' and request.topic=='A' and request.task=='utterance': raise RuntimeError('private-provider-sentinel')
            if request.task=='host_control':
                action='end' if self.mode=='host_end' and len(request.messages)>=2 else 'linking' if self.mode=='linking' and request.messages[-1].kind=='statement' else 'followup'
                return {'task':'host_control','action':action,'public_focus':'邀请专家说明边界'}
            if request.task=='intent':
                actor=next(p for p in request.participants if p.id==request.actor_id)
                target=next((m.id for m in reversed(request.messages) if m.participant_id!=actor.id),None)
                if self.mode=='bad_intent': return {'task':'intent','kind':'REBUT','target_message_id':str(uuid4()),'relevance':90,'public_focus':'公开'}
                kind='PASS' if self.mode=='pass' or actor.name!='林衡' and len(request.messages)==1 else self.mode if self.mode in ('REQUEST','INTERRUPT','SUPPLEMENT','REBUT') else 'REQUEST'
                return {'task':'intent','kind':kind,'target_message_id':target if kind in ('SUPPLEMENT','REBUT') else None,'relevance':100 if actor.name=='林衡' else 70,'public_focus':actor.stance}
            if request.task=='utterance':
                if self.mode=='transient' and request.participation_kind and sum(r.participation_kind is not None for r in self.requests)==1:
                    return {'task':'utterance','sentences':[]}
                if self.mode in ('long','timeout','exception') and request.participation_kind:
                    if self.mode=='long': return {'task':'utterance','sentences':['长'*201]}
                    if self.mode=='timeout': await asyncio.sleep(3)
                    if self.mode=='exception': raise RuntimeError('private-provider-sentinel')
                if self.mode=='time' and request.participation_kind:
                    with self.repository.database.connect() as conn: conn.execute("UPDATE runs SET started_at='2000-01-01T00:00:00Z' WHERE id=?",(str(request.run_id),))
                purpose=request.host_task or request.participation_kind
                return {'task':'utterance','sentences':[f'模拟公开发言，当前任务为{purpose}。']}
            return await super().generate(request)
        finally: self.active-=1


@pytest.fixture
def engine_setup(tmp_path):
    clients=[]; gateways=[]
    def build(mode='REQUEST',gate=False,**kwargs):
        gateway=ControlledGateway(mode,gate)
        settings=Settings(_env_file=None,database_path=tmp_path/f'{len(clients)}.sqlite3',model_timeout_seconds=kwargs.pop('model_timeout_seconds',1),discussion_max_turns=kwargs.pop('discussion_max_turns',5),**kwargs)
        context=TestClient(create_app(settings),raise_server_exceptions=False)
        client=context.__enter__(); clients.append(context); gateways.append(gateway)
        client.app.state.model_gateway=gateway; gateway.repository=client.app.state.repository
        return client,gateway
    yield build
    for gateway in gateways: gateway.release.set()
    for context in reversed(clients): context.__exit__(None,None,None)


def start_ready(client,topic='自动讨论'):
    did=create(client,topic)['discussion']['id']; generate(client,did); wait_for(client,did,'READY')
    return did,start(client,did)


@pytest.mark.parametrize('kind',['REQUEST','INTERRUPT','SUPPLEMENT','REBUT'])
def test_automatic_opening_and_expert_request_transfer(kind,engine_setup):
    client,gateway=engine_setup(kind,discussion_max_turns=3)
    did,accepted=start_ready(client)
    snapshot=wait_for(client,did,'SUMMARIZING')
    assert [m['turn_no'] for m in snapshot['messages']]==[1,2,3]
    assert snapshot['messages'][0]['kind']=='opening'
    assert all(r.messages and r.messages[0].kind=='opening' for r in gateway.requests if r.task=='intent')
    experts=[r for r in gateway.requests if r.task=='utterance' and r.participation_kind]
    assert experts[0].participation_kind==kind
    if kind in ('SUPPLEMENT','REBUT'): assert experts[0].target_message_id==snapshot['messages'][0]['id'] or str(experts[0].target_message_id)==snapshot['messages'][0]['id']
    assert all(r.discussion_id==experts[0].discussion_id and str(r.run_id)==accepted['run_id'] for r in gateway.requests)
    assert all(r.state=='IDLE' for r in client.app.state.repository.snapshot(experts[0].discussion_id).role_states)
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT summary_through_turn FROM runs WHERE id=?',(accepted['run_id'],)).fetchone()[0]==3


def test_no_participants_causes_host_followup_and_linking_occurs_after_expert(engine_setup):
    client,gateway=engine_setup('pass',discussion_max_turns=3)
    did,_=start_ready(client); snapshot=wait_for(client,did,'SUMMARIZING')
    assert [m['kind'] for m in snapshot['messages']]==['opening','followup','followup']
    assert [r.host_task for r in gateway.requests if r.task=='utterance']==['opening','followup','followup']
    other,gateway2=engine_setup('linking',discussion_max_turns=4)
    did2,_=start_ready(other); snapshot2=wait_for(other,did2,'SUMMARIZING')
    assert [m['kind'] for m in snapshot2['messages']][:3]==['opening','statement','linking']


def test_host_end_freezes_boundary_without_summary_or_extra_utterance(engine_setup):
    client,gateway=engine_setup('host_end',discussion_max_turns=20)
    did,accepted=start_ready(client); snapshot=wait_for(client,did,'SUMMARIZING')
    assert len(snapshot['messages'])==2 and snapshot['summary'] is None and snapshot['insights']['items']==[]
    assert not any(r.task=='summary' for r in gateway.requests)  # 4C-1 may extract an empty batch.
    before=len(gateway.requests); assert start(client,did)==accepted
    time.sleep(.03)
    assert len(gateway.requests)==before
    with client.app.state.database.connect() as conn: assert tuple(conn.execute('SELECT summary_through_turn,stop_reason FROM runs WHERE id=?',(accepted['run_id'],)).fetchone())==(2,'host_end')


def test_same_and_different_duplicate_start_only_register_one_background_run_task(engine_setup):
    client,gateway=engine_setup(gate=True)
    did=create(client)['discussion']['id']; generate(client,did); wait_for(client,did,'READY')
    key=uuid4()
    with ThreadPoolExecutor(max_workers=3) as pool:
        accepted=list(pool.map(lambda k:start(client,did,k),[key,key,uuid4()]))
    assert accepted[0]==accepted[1]==accepted[2]
    end=time.monotonic()+2
    while not gateway.requests and time.monotonic()<end: time.sleep(.005)
    assert len(client.app.state.tasks.run_tasks)==1
    assert sum(r.host_task=='opening' for r in gateway.requests)==1
    gateway.release.set(); wait_for(client,did,'SUMMARIZING')


def test_public_speaker_exclusive_and_recent_occupancy_prevents_continuous_expert(engine_setup):
    client,gateway=engine_setup(discussion_max_turns=6)
    did,_=start_ready(client); snapshot=wait_for(client,did,'SUMMARIZING')
    people={p['id']:p for p in snapshot['participants']}
    for a,b in zip(snapshot['messages'],snapshot['messages'][1:]):
        if people[a['participant_id']]['kind']=='EXPERT': assert a['participant_id']!=b['participant_id']
    public_states={p['id']:'IDLE' for p in snapshot['participants']}
    for event in events(client,did):
        if event['type']=='participant.status_changed':
            public_states[event['payload']['participant_id']]=event['payload']['state']
            assert sum(s=='SPEAKING' for s in public_states.values())<=1
    assert len({m['id'] for m in snapshot['messages']})==6
    assert [m['turn_no'] for m in snapshot['messages']]==list(range(1,7))


@pytest.mark.parametrize('mode,code',[('long','MODEL_RESULT_INVALID'),('timeout','MODEL_TIMEOUT'),('exception','TASK_FAILED'),('bad_intent','MODEL_RESULT_INVALID')])
def test_bounded_failures_preserve_opening_and_expose_safe_code(engine_setup,mode,code,caplog):
    client,gateway=engine_setup(mode)
    did,_=start_ready(client); failed=wait_for(client,did,'FAILED')
    assert failed['discussion']['failure_code']==code and len(failed['messages'])==1
    assert failed['discussion']['failure_stage']=='discussion'
    assert all(r['state']=='IDLE' for r in failed['role_states'])
    if mode!='bad_intent': assert len([r for r in gateway.requests if r.participation_kind])==2
    else: assert len([r for r in gateway.requests if r.task=='intent'])==8
    assert 'private-provider-sentinel' not in caplog.text+json.dumps(events(client,did))+json.dumps(failed)


def test_write_failure_leaves_no_message_or_success_event_and_run_fails(engine_setup):
    client,gateway=engine_setup(gate=True)
    did,_=start_ready(client)
    with client.app.state.database.connect() as conn: conn.execute("CREATE TRIGGER reject_turn BEFORE INSERT ON events WHEN NEW.type='turn.committed' BEGIN SELECT RAISE(ABORT,'private-write-sentinel'); END")
    gateway.release.set(); failed=wait_for(client,did,'FAILED')
    assert failed['messages']==[] and failed['discussion']['failure_code']=='DATABASE_UNAVAILABLE'
    assert all(e['type']!='turn.committed' for e in events(client,did))


def test_two_runs_interleave_and_one_failure_does_not_stop_other(engine_setup):
    client,gateway=engine_setup('fail_A',gate=True)
    a=create(client,'A')['discussion']['id']; b=create(client,'B')['discussion']['id']
    generate(client,a); generate(client,b); wait_for(client,a,'READY'); wait_for(client,b,'READY')
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda did:start(client,did),[a,b]))
    deadline=time.monotonic()+3
    while len(gateway.requests)<2 and time.monotonic()<deadline: time.sleep(.005)
    assert gateway.active==2
    gateway.release.set()
    failed=wait_for(client,a,'FAILED'); success=wait_for(client,b,'SUMMARIZING')
    assert failed['messages']==[] and len(success['messages'])==5
    for did in [a,b]:
        snapshot=client.get(f'/api/discussions/{did}').json()
        assert all(m['discussion_id']==did and m['run_id']==snapshot['discussion']['run_id'] for m in snapshot['messages'])
        assert all(e['discussion_id']==did and e['run_id'] in (None,snapshot['discussion']['run_id']) for e in events(client,did))
    topics=[r.topic for r in gateway.requests]
    assert 'A' in topics[:4] and 'B' in topics[:4]


def test_expired_in_flight_utterance_moves_to_summarizing_and_never_commits(engine_setup):
    client,gateway=engine_setup('time')
    did,_=start_ready(client); snapshot=wait_for(client,did,'SUMMARIZING')
    assert len(snapshot['messages'])==1 and snapshot['messages'][0]['kind']=='opening'
    assert all(r['state']=='IDLE' for r in snapshot['role_states'])


def test_interrupted_model_result_is_rejected_and_close_collects_all_run_tasks(engine_setup):
    client,gateway=engine_setup(gate=True)
    did,accepted=start_ready(client)
    end=time.monotonic()+2
    while not gateway.requests and time.monotonic()<end: time.sleep(.005)
    client.app.state.repository.recover_unfinished()
    gateway.release.set()
    snapshot=wait_for(client,did,'INTERRUPTED')
    time.sleep(.03)
    assert client.get(f'/api/discussions/{did}').json()['messages']==[]
    client.portal.call(client.app.state.tasks.close)
    assert not client.app.state.tasks.run_tasks and not client.app.state.tasks.database_workers and gateway.active==0


def test_transient_invalid_utterance_retries_same_claim_then_commits_once(engine_setup):
    client,gateway=engine_setup('transient',discussion_max_turns=2)
    did,_=start_ready(client); snapshot=wait_for(client,did,'SUMMARIZING')
    requests=[r for r in gateway.requests if r.participation_kind]
    assert len(requests)==2 and requests[0]==requests[1]
    assert len(snapshot['messages'])==2
    assert sum(e['type']=='turn.committed' for e in events(client,did))==2


def test_real_run_deadline_cancels_slow_model_without_failure_or_retry(engine_setup):
    client,gateway=engine_setup(gate=True,model_timeout_seconds=30,discussion_max_seconds=10)
    began=time.monotonic(); did,accepted=start_ready(client)
    snapshot=wait_for(client,did,'SUMMARIZING',timeout=12)
    assert time.monotonic()-began<12
    assert snapshot['messages']==[] and len(gateway.requests)==1 and gateway.active==0
    assert all(r['state']=='IDLE' for r in snapshot['role_states'])
    with client.app.state.database.connect() as conn:
        assert tuple(conn.execute('SELECT summary_through_turn,stop_reason FROM runs WHERE id=?',(accepted['run_id'],)).fetchone())==(0,'time_limit')
