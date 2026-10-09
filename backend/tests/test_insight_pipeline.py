"""4C-1 scoped evidence, monotone batches and live real FastAPI/SQLite updates."""
import asyncio
import threading
import time
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import IntentResult
from backend.app.lifecycle import RepositoryUnavailable
from backend.app.main import create_app
from backend.app.model_gateway import InvalidModelResult, validate_result
from backend.tests.test_discussion_engine import ControlledGateway, start_ready
from backend.tests.test_roster_tasks import setup, events, wait_for
from backend.tests.test_turn_transactions import running, opening


def statement(repo, did, rid, index=0):
    context = repo.begin_cycle(did, rid)
    person = [p for p in context.snapshot.participants if p.kind == 'EXPERT'][index]
    assert repo.record_intents(context, {person.id: IntentResult(task='intent', kind='REQUEST', relevance=80, public_focus='成本与试点')})
    claim = repo.prepare_turn(context, person.id, participation_kind='REQUEST')
    assert repo.mark_speaking(context, claim.id)
    assert repo.commit_turn(context, claim.id, {'task':'utterance', 'sentences':['认可先试点，但成本边界需要继续验证。']})


def evidence(request, kind='consensus'):
    experts = {p.id for p in request.participants if p.kind == 'EXPERT'}
    sources = []
    actors = set()
    for message in request.messages:
        if message.participant_id in experts and message.participant_id not in actors:
            sources.append(message.id); actors.add(message.participant_id)
    return {'task':'insights', 'items': [] if len(actors)<2 else [
        {'id':str(uuid4()), 'kind':kind, 'content':'两位专家认可先进行小规模试点。' if kind=='consensus' else '执行成本的边界仍未解决。', 'source_message_ids':sources[:2]}]}


def prepared(setup):
    client, repo, did, rid = running(setup)
    opening(repo, did, rid); statement(repo, did, rid, 0); statement(repo, did, rid, 1)
    return client, repo, did, rid


def test_evidence_batch_and_event_commit_once_and_snapshot_returns_latest(setup):
    client, repo, did, rid = prepared(setup)
    claim = repo.claim_insights(did, rid)
    assert claim.request.through_turn == 3 and claim.request.insight_version == 1
    assert repo.complete_insights(claim, evidence(claim.request))
    assert repo.complete_insights(claim, evidence(claim.request)) is False
    assert repo.claim_insights(did, rid) is None
    snapshot = repo.snapshot(did)
    assert snapshot.insights.version == 1 and snapshot.insights.through_turn == 3
    assert len(snapshot.insights.items) == 1
    assert snapshot.insight_status.state == 'SUCCEEDED'
    assert sum(e['type']=='insights.updated' for e in events(client,str(did))) == 1
    with repo.database.connect() as conn: assert not conn.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('case', ['single_expert','host_only','foreign_source','future_source','duplicate_source'])
def test_invalid_evidence_does_not_write_batch(setup, case):
    client, repo, did, rid = prepared(setup)
    claim = repo.claim_insights(did,rid); raw = evidence(claim.request)
    if case == 'single_expert': raw['items'][0]['source_message_ids']=[claim.request.messages[1].id]
    if case == 'host_only': raw['items'][0]['source_message_ids']=[claim.request.messages[0].id]
    if case == 'foreign_source': raw['items'][0]['source_message_ids'][0]=uuid4()
    if case == 'future_source':
        statement(repo,did,rid,2); raw['items'][0]['source_message_ids'][0]=repo.snapshot(did).messages[-1].id
    if case == 'duplicate_source': raw['items'][0]['source_message_ids']*=2
    with pytest.raises(InvalidModelResult): repo.complete_insights(claim,raw)
    assert repo.snapshot(did).insights.version == 0
    assert not any(e['type']=='insights.updated' for e in events(client,str(did)))


def test_empty_evidence_is_valid_and_old_result_cannot_replace_new_version(setup):
    client, repo, did, rid = prepared(setup)
    old = repo.claim_insights(did,rid)
    statement(repo,did,rid,2)
    new = repo.claim_insights(did,rid)
    assert new.request.insight_version == 2
    assert repo.complete_insights(old,evidence(old.request)) is False
    assert repo.complete_insights(new,{'task':'insights','items':[]})
    assert repo.snapshot(did).insights.version == 2 and repo.snapshot(did).insights.items == ()


@pytest.mark.parametrize('table', ['insights', 'events'])
def test_insight_write_failure_rolls_back_batch_sources_and_event(setup,table):
    client,repo,did,rid=prepared(setup); claim=repo.claim_insights(did,rid)
    before=repo.snapshot(did)
    with repo.database.connect() as conn:
        condition="WHEN NEW.type='insights.updated'" if table=='events' else ''
        conn.execute(f"CREATE TRIGGER break_insight BEFORE INSERT ON {table} {condition} BEGIN SELECT RAISE(ABORT,'test write failure'); END")
    with pytest.raises(RepositoryUnavailable): repo.complete_insights(claim,evidence(claim.request))
    assert repo.snapshot(did)==before
    with repo.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM insight_batches').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM insight_sources').fetchone()[0]==0


def test_failure_keeps_previous_evidence_and_interruption_rejects_late_result(setup):
    client,repo,did,rid=prepared(setup); first=repo.claim_insights(did,rid)
    assert repo.complete_insights(first,evidence(first.request))
    statement(repo,did,rid,2); second=repo.claim_insights(did,rid)
    assert repo.fail_insights(second,'MODEL_TIMEOUT')
    assert repo.snapshot(did).insights.version==1
    assert repo.snapshot(did).insight_status.error_code=='MODEL_TIMEOUT'
    statement(repo,did,rid,0); late=repo.claim_insights(did,rid)
    repo.recover_unfinished()
    assert repo.complete_insights(late,evidence(late.request)) is False
    assert repo.snapshot(did).insights.version==1


class SynthesisGateway(ControlledGateway):
    def __init__(self, insight_mode='valid'):
        super().__init__('REQUEST')
        self.insight_mode=insight_mode
        self.summary_release=threading.Event()
        self.summary_calls=[]

    async def generate(self,request):
        if request.task=='insights':
            self.requests.append(request)
            # Assert model IO is outside SQLite's writer transaction.
            with self.repository.database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE'); conn.execute('ROLLBACK')
            if self.insight_mode=='timeout': await asyncio.sleep(3)
            if self.insight_mode=='invalid' and request.through_turn>=6:
                return {'task':'insights','items':[{'id':str(uuid4()),'kind':'consensus','content':'错误引用','source_message_ids':[str(uuid4())]}]}
            raw=evidence(request)
            if raw['items']:
                raw['items'].append({**raw['items'][0], 'id':str(uuid4()), 'kind':'disagreement', 'content':'成本上限仍待验证。'})
            return raw
        if request.task=='summary':
            self.summary_calls.append(request)
            while not self.summary_release.is_set(): await asyncio.sleep(.005)
            return {'task':'summary','content':'专家认可先进行试点，成本上限仍有分歧，需继续验证。'}
        return await super().generate(request)


@pytest.fixture
def synthesis_client(tmp_path):
    opened=[]; gateways=[]
    def build(gateway=None,**kwargs):
        gateway=gateway or SynthesisGateway()
        settings=Settings(_env_file=None,database_path=tmp_path/f'{len(opened)}.sqlite3',model_timeout_seconds=kwargs.pop('model_timeout_seconds',1),discussion_max_turns=kwargs.pop('discussion_max_turns',7),**kwargs)
        context=TestClient(create_app(settings),raise_server_exceptions=False)
        client=context.__enter__(); opened.append(context); gateways.append(gateway)
        client.app.state.model_gateway=gateway; gateway.repository=client.app.state.repository
        return client,gateway
    yield build
    for gateway in gateways: gateway.summary_release.set(); gateway.release.set()
    for context in reversed(opened): context.__exit__(None,None,None)


def test_two_nonempty_insight_updates_occur_while_running_and_final_boundary_is_extracted(synthesis_client):
    client,gateway=synthesis_client(); did,_=start_ready(client)
    snapshot=wait_for(client,did,'SUMMARIZING')
    snapshot=wait_projection(client,did,lambda s:s['insights']['through_turn']==7)
    stream=events(client,did); state='DRAFT'; live=[]
    for event in stream:
        if event['type']=='discussion.state_changed': state=event['payload']['state']
        if event['type']=='insights.updated' and event['payload']['items']:
            if state=='RUNNING': live.append(event['payload']['through_turn'])
    assert live==[4,6]
    assert snapshot['insights']['through_turn']==7
    assert [r.through_turn for r in gateway.requests if r.task=='insights']==[2,4,6,7]


def test_failed_extraction_preserves_previous_batch_and_discussion_still_ends(synthesis_client):
    client,gateway=synthesis_client(SynthesisGateway('invalid')); did,_=start_ready(client)
    snapshot=wait_for(client,did,'SUMMARIZING')
    snapshot=wait_projection(client,did,lambda s:s['insight_status']['through_turn']==7 and s['insight_status']['state']=='FAILED')
    assert snapshot['insights']['through_turn']==4
    assert snapshot['insight_status']['state']=='FAILED'
    assert snapshot['insight_status']['error_code']=='MODEL_RESULT_INVALID'
    assert len([r for r in gateway.requests if r.task=='insights' and r.through_turn==6])==2
    assert len(snapshot['messages'])==7


def wait_projection(client,did,predicate,timeout=6):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        response=client.get(f'/api/discussions/{did}')
        assert response.status_code==200,response.text
        snapshot=response.json()
        if predicate(snapshot): return snapshot
        time.sleep(.01)
    raise AssertionError(f'projection did not settle: {snapshot}')


def test_insight_timeout_is_bounded_and_does_not_stop_discussion(synthesis_client):
    client,gateway=synthesis_client(SynthesisGateway('timeout'),discussion_max_turns=3,insight_max_seconds=1)
    did,_=start_ready(client)
    snapshot=wait_projection(client,did,lambda s:s['discussion']['state']=='SUMMARIZING' and s['insight_status']['through_turn']==3 and s['insight_status']['state']=='FAILED')
    assert len(snapshot['messages'])==3 and snapshot['insight_status']['error_code']=='MODEL_TIMEOUT'
    assert len([r for r in gateway.requests if r.task=='insights'])==2  # One attempt per 1s total budget.


def test_actual_cross_discussion_source_is_rejected(setup):
    client,repo,did,rid=prepared(setup)
    from backend.tests.test_start_recovery import ready
    from backend.app.contracts import StartDiscussion
    foreign,_=ready(client,'另一场')
    run=repo.start(UUID(foreign),StartDiscussion(roster_revision=1),uuid4(),client.app.state.tasks.settings).body
    opening(repo,UUID(foreign),UUID(run['run_id']))
    claim=repo.claim_insights(did,rid); raw=evidence(claim.request)
    raw['items'][0]['source_message_ids'][0]=repo.snapshot(UUID(foreign)).messages[0].id
    with pytest.raises(InvalidModelResult): repo.complete_insights(claim,raw)
    assert repo.snapshot(did).insights.version==0
