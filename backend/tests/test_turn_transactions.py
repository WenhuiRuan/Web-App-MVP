"""4B-2 real SQLite turn claims, stale guards and atomic public projection."""
from uuid import UUID,uuid4

import pytest

from backend.app.contracts import IntentResult,StartDiscussion
from backend.app.lifecycle import LifecycleError,RepositoryUnavailable
from backend.tests.test_roster_tasks import setup,events
from backend.tests.test_start_recovery import ready,start


def running(setup,**settings):
    client,gateway=setup(**settings)
    did,_=ready(client)
    repo=client.app.state.repository
    accepted=repo.start(UUID(did),StartDiscussion(roster_revision=1),uuid4(),client.app.state.tasks.settings).body
    return client,repo,UUID(did),UUID(accepted['run_id'])


def opening(repo,did,rid):
    context=repo.begin_cycle(did,rid)
    host=next(p for p in context.snapshot.participants if p.kind=='HOST')
    claim=repo.prepare_turn(context,host.id,host_task='opening')
    assert repo.mark_speaking(context,claim.id)
    assert repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['我们先梳理问题。']})
    return claim


def test_turn_claim_and_message_commit_are_atomic_ordered_and_idempotent(setup):
    client,repo,did,rid=running(setup)
    context=repo.begin_cycle(did,rid)
    host=context.snapshot.participants[0]
    claim=repo.prepare_turn(context,host.id,host_task='opening')
    assert repo.snapshot(did).role_states[0].state in ('IDLE','PREPARING')
    assert repo.mark_speaking(context,claim.id)
    assert repo.mark_speaking(context,claim.id) is False
    assert sum(r.state=='SPEAKING' for r in repo.snapshot(did).role_states)==1
    assert repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['讨论成本。','也讨论价值。']})
    assert repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['重复。']}) is False
    snapshot=repo.snapshot(did)
    assert len(snapshot.messages)==1 and snapshot.messages[0].id==claim.id
    assert snapshot.messages[0].turn_no==1 and snapshot.messages[0].kind=='opening'
    assert all(r.state=='IDLE' for r in snapshot.role_states)
    stream=events(client,str(did))
    assert sum(e['type']=='turn.committed' for e in stream)==1
    assert [e['seq'] for e in stream]==list(range(1,len(stream)+1))
    assert not any('reasoning' in str(e) for e in stream)


def test_intents_are_scoped_persisted_once_and_only_selected_actor_can_be_claimed(setup):
    client,repo,did,rid=running(setup); opening(repo,did,rid)
    context=repo.begin_cycle(did,rid)
    experts=[p for p in context.snapshot.participants if p.kind=='EXPERT']
    values={p.id:IntentResult(task='intent',kind='REBUT' if i==0 else 'PASS',target_message_id=context.snapshot.messages[0].id if i==0 else None,relevance=70,public_focus='关注成本') for i,p in enumerate(experts)}
    assert repo.record_intents(context,values)
    assert repo.record_intents(context,values) is False
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM speaking_intents').fetchone()[0]==4
    claim=repo.prepare_turn(context,experts[0].id,participation_kind='REBUT',target_message_id=context.snapshot.messages[0].id,public_focus='关注成本')
    assert claim.request.participation_kind=='REBUT' and claim.request.cycle==context.cycle
    with pytest.raises(LifecycleError): repo.prepare_turn(context,experts[1].id,participation_kind='REQUEST')
    assert repo.mark_speaking(context,claim.id)
    assert repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['成本需要分情形验证。']})


@pytest.mark.parametrize('invalid',['foreign_actor','foreign_target','wrong_kind'])
def test_invalid_intent_or_claim_context_never_writes(setup,invalid):
    client,repo,did,rid=running(setup); opening(repo,did,rid); context=repo.begin_cycle(did,rid)
    actor=next(p.id for p in context.snapshot.participants if p.kind=='EXPERT')
    result=IntentResult(task='intent',kind='REBUT',target_message_id=context.snapshot.messages[0].id,relevance=80,public_focus='公开关注')
    if invalid=='foreign_actor': actor=uuid4()
    if invalid=='foreign_target': result=result.model_copy(update={'target_message_id':uuid4()})
    if invalid=='wrong_kind': result=result.model_copy(update={'kind':'PASS'})
    with pytest.raises(LifecycleError): repo.record_intents(context,{actor:result})
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM speaking_intents').fetchone()[0]==0


def test_stale_cycle_foreign_run_and_interrupted_callback_cannot_commit(setup):
    client,repo,did,rid=running(setup)
    old=repo.begin_cycle(did,rid); current=repo.begin_cycle(did,rid)
    assert repo.prepare_turn(old,old.snapshot.participants[0].id,host_task='opening') is None
    assert repo.begin_cycle(did,uuid4()) is None
    claim=repo.prepare_turn(current,current.snapshot.participants[0].id,host_task='opening')
    assert repo.mark_speaking(current,claim.id)
    repo.recover_unfinished()
    assert repo.commit_turn(current,claim.id,{'task':'utterance','sentences':['迟到。']}) is False
    assert repo.snapshot(did).messages==()


@pytest.mark.parametrize('target',['message','event'])
def test_failed_turn_write_preserves_speaking_claim_and_previous_messages(setup,target):
    client,repo,did,rid=running(setup); opening(repo,did,rid)
    context=repo.begin_cycle(did,rid)
    claim=repo.prepare_turn(context,context.snapshot.participants[0].id,host_task='followup')
    repo.mark_speaking(context,claim.id)
    with client.app.state.database.connect() as conn:
        trigger="BEFORE INSERT ON messages" if target=='message' else "BEFORE INSERT ON events WHEN NEW.type='turn.committed'"
        conn.execute(f"CREATE TRIGGER reject_turn {trigger} BEGIN SELECT RAISE(ABORT,'private-write-sentinel'); END")
    before=repo.snapshot(did)
    with pytest.raises(RepositoryUnavailable): repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['请补充边界。']})
    after=repo.snapshot(did)
    assert after==before
    assert sum(e['type']=='turn.committed' for e in events(client,str(did)))==1
    with client.app.state.database.connect() as conn: conn.execute('DROP TRIGGER reject_turn')
    assert repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['请补充边界。']})


@pytest.mark.parametrize('raw',[{'task':'utterance','sentences':['x'*201]}, {'task':'utterance','sentences':['一。二。']},{'task':'utterance','sentences':['一。','二。','三。']}])
def test_invalid_utterance_keeps_committed_data_unchanged(setup,raw):
    from backend.app.model_gateway import InvalidModelResult
    client,repo,did,rid=running(setup); context=repo.begin_cycle(did,rid)
    claim=repo.prepare_turn(context,context.snapshot.participants[0].id,host_task='opening'); repo.mark_speaking(context,claim.id)
    before=repo.snapshot(did)
    with pytest.raises(InvalidModelResult): repo.commit_turn(context,claim.id,raw)
    assert repo.snapshot(did)==before


def test_turn_limit_atomically_freezes_summary_boundary_and_rejects_new_messages(setup):
    client,repo,did,rid=running(setup,discussion_max_turns=1)
    opening(repo,did,rid)
    assert repo.snapshot(did).discussion.state=='SUMMARIZING'
    assert repo.begin_cycle(did,rid) is None
    with client.app.state.database.connect() as conn:
        row=conn.execute('SELECT summary_through_turn,stop_reason FROM runs WHERE id=?',(str(rid),)).fetchone()
        assert tuple(row)==(1,'turn_limit')


@pytest.mark.parametrize('when',['before_cycle','in_flight'])
def test_time_budget_blocks_new_or_in_flight_commit_and_freezes_actual_boundary(setup,when):
    client,repo,did,rid=running(setup)
    if when=='in_flight':
        context=repo.begin_cycle(did,rid)
        claim=repo.prepare_turn(context,context.snapshot.participants[0].id,host_task='opening'); repo.mark_speaking(context,claim.id)
    with client.app.state.database.connect() as conn: conn.execute("UPDATE runs SET started_at='2000-01-01T00:00:00Z' WHERE id=?",(str(rid),))
    if when=='in_flight': assert repo.commit_turn(context,claim.id,{'task':'utterance','sentences':['超时返回。']}) is False
    else: assert repo.begin_cycle(did,rid) is None
    snapshot=repo.snapshot(did)
    assert snapshot.discussion.state=='SUMMARIZING' and not snapshot.messages
    assert all(r.state=='IDLE' for r in snapshot.role_states)


def test_host_end_and_failure_keep_boundary_and_safe_error_state(setup):
    client,repo,did,rid=running(setup); opening(repo,did,rid)
    assert repo.finish_run(did,rid,'host_end')
    assert repo.finish_run(did,rid,'host_end') is False
    assert repo.fail_run(did,rid,'TASK_FAILED') is False
    assert repo.snapshot(did).discussion.state=='SUMMARIZING'


def test_run_failure_preserves_messages_resets_roles_and_persists_error(setup):
    client,repo,did,rid=running(setup); opening(repo,did,rid)
    context=repo.begin_cycle(did,rid)
    assert repo.fail_run(did,rid,'MODEL_TIMEOUT')
    snapshot=repo.snapshot(did)
    assert snapshot.discussion.state=='FAILED' and snapshot.discussion.failure_code=='MODEL_TIMEOUT'
    assert len(snapshot.messages)==1 and all(r.state=='IDLE' for r in snapshot.role_states)
    assert events(client,str(did))[-2]['type']=='operation.failed'
