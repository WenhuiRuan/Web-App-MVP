"""4B-1 pure arbitration and explicit model task context, written before implementation."""
import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.contracts import ModelRequest, IntentResult, Message, Snapshot
from backend.app.model_gateway import DeterministicModelGateway, InvalidModelResult, validate_result


@pytest.fixture
def panel():
    req=ModelRequest(task='roster',discussion_id=uuid4(),topic='调度测试')
    people=asyncio.run(DeterministicModelGateway().generate(req)).participants
    rid=uuid4()
    opening=Message(id=uuid4(),discussion_id=req.discussion_id,run_id=rid,participant_id=people[0].id,turn_no=1,kind='opening',content='请从不同角度讨论。',created_at='2026-10-09T00:00:00Z')
    snapshot=Snapshot(discussion=dict(id=req.discussion_id,topic=req.topic,expert_count=4,state='RUNNING',version=3,roster_revision=1,run_id=rid,created_at=opening.created_at,updated_at=opening.created_at),participants=people,messages=[opening],last_event_seq=5)
    return snapshot


def intent(kind='REQUEST',relevance=70,target=None):
    return IntentResult(task='intent',kind=kind,relevance=relevance,target_message_id=target,public_focus='公开：关注成本和影响')


def request(panel,actor=None,**kwargs):
    return ModelRequest(task='utterance',discussion_id=panel.discussion.id,run_id=panel.discussion.run_id,topic=panel.discussion.topic,participants=panel.participants,messages=panel.messages,actor_id=actor or panel.participants[1].id,cycle=1,**kwargs)


@pytest.mark.parametrize('kind',['REQUEST','INTERRUPT','SUPPLEMENT','REBUT'])
def test_explicit_participation_and_response_target_reach_model_request(panel,kind):
    req=request(panel,participation_kind=kind,target_message_id=panel.messages[0].id if kind in ('SUPPLEMENT','REBUT') else None)
    assert req.participation_kind==kind
    assert req.model_dump(mode='json')['cycle']==1


@pytest.mark.parametrize('task',['opening','followup','linking'])
def test_host_utterance_has_explicit_task_and_no_expert_intent(panel,task):
    req=request(panel,actor=panel.participants[0].id,host_task=task)
    assert req.host_task==task and req.participation_kind is None


@pytest.mark.parametrize('kwargs',[
    {}, {'participation_kind':'PASS'}, {'participation_kind':'REBUT'},
    {'participation_kind':'REQUEST','host_task':'opening'},
    {'participation_kind':'SUPPLEMENT','target_message_id':uuid4()},
])
def test_invalid_utterance_task_context_is_rejected(panel,kwargs):
    with pytest.raises(ValidationError): request(panel,**kwargs)


def test_host_and_expert_task_identity_cannot_be_swapped(panel):
    with pytest.raises(ValidationError): request(panel,actor=panel.participants[0].id,participation_kind='REQUEST')
    with pytest.raises(ValidationError): request(panel,host_task='followup')


def test_arbitration_uses_relevance_and_response_relation_not_fixed_roster_order(panel):
    from backend.app.scheduling import choose_speaker
    a,b=panel.participants[1:3]
    assert choose_speaker(panel,{a.id:intent(relevance=20),b.id:intent(relevance=90)})==b.id
    assert choose_speaker(panel,{a.id:intent('REBUT',75,panel.messages[0].id),b.id:intent(relevance=80)})==a.id
    assert choose_speaker(panel,{a.id:intent('SUPPLEMENT',75,panel.messages[0].id),b.id:intent('INTERRUPT',75)})==a.id


def test_pass_and_no_intents_select_host_fallback(panel):
    from backend.app.scheduling import choose_speaker
    assert choose_speaker(panel,{}) is None
    assert choose_speaker(panel,{panel.participants[1].id:intent('PASS')}) is None


def test_consecutive_occupancy_is_blocked_and_other_candidate_can_speak(panel):
    from backend.app.scheduling import choose_speaker
    a,b=panel.participants[1:3]
    last=panel.messages[0].model_copy(update={'id':uuid4(),'participant_id':a.id,'turn_no':2,'kind':'statement'})
    current=panel.model_copy(update={'messages':(*panel.messages,last)})
    assert choose_speaker(current,{a.id:intent(relevance=100),b.id:intent(relevance=30)})==b.id
    assert choose_speaker(current,{a.id:intent(relevance=100)}) is None


def test_recent_usage_penalty_changes_equal_relevance_and_ties_are_stable(panel):
    from backend.app.scheduling import choose_speaker
    a,b=panel.participants[1:3]
    m=panel.messages[0]
    messages=(*panel.messages,m.model_copy(update={'id':uuid4(),'participant_id':a.id,'turn_no':2,'kind':'statement'}),m.model_copy(update={'id':uuid4(),'turn_no':3,'kind':'followup'}))
    current=panel.model_copy(update={'messages':messages})
    assert choose_speaker(current,{a.id:intent(),b.id:intent()})==b.id
    assert choose_speaker(panel,{a.id:intent(),b.id:intent()})==choose_speaker(panel,{b.id:intent(),a.id:intent()})


@pytest.mark.parametrize('case',['foreign_actor','host_actor','foreign_target','self_target'])
def test_invalid_intent_cannot_enter_arbitration(panel,case):
    from backend.app.scheduling import choose_speaker
    from backend.app.lifecycle import LifecycleError
    actor=panel.participants[1].id
    current=panel
    result=intent()
    if case=='foreign_actor': actor=uuid4()
    if case=='host_actor': actor=panel.participants[0].id
    if case=='foreign_target': result=intent('REBUT',70,uuid4())
    if case=='self_target':
        m=panel.messages[0].model_copy(update={'participant_id':actor,'kind':'statement'})
        current=panel.model_copy(update={'messages':(m,)})
        result=intent('REBUT',70,m.id)
    with pytest.raises(LifecycleError): choose_speaker(current,{actor:result})


@pytest.mark.parametrize('count,limit,elapsed,seconds,expected',[(19,20,1,300,None),(20,20,1,300,'turn_limit'),(2,20,300,300,'time_limit')])
def test_exact_end_boundaries(count,limit,elapsed,seconds,expected):
    from backend.app.scheduling import stop_reason
    assert stop_reason(count,limit,elapsed,seconds)==expected


def test_gateway_rejects_self_response_and_pass_with_target(panel):
    actor=panel.participants[1]
    m=panel.messages[0].model_copy(update={'participant_id':actor.id,'kind':'statement'})
    req=ModelRequest(task='intent',discussion_id=panel.discussion.id,run_id=panel.discussion.run_id,topic=panel.discussion.topic,participants=panel.participants,messages=[m],actor_id=actor.id,cycle=1)
    for raw in [intent('REBUT',70,m.id),intent('PASS',70,m.id)]:
        with pytest.raises(InvalidModelResult): validate_result(req,raw)
