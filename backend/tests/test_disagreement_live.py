"""Evidence-side distinction and bounded process publication; no paid requests."""
import asyncio
import json
from pathlib import Path
from uuid import UUID,uuid4

import httpx
import pytest

from backend.app.contracts import ModelRequest,Participant,Message
from backend.app.deepseek_gateway import DeepSeekGateway,bind_result,reviewed_points
from backend.app.tasks import TaskSupervisor
from backend.tests.test_deepseek import answer,config,checks
from backend.tests.test_insight_pipeline import prepared,statement,evidence
from backend.tests.test_roster_tasks import setup,events

ROOT=Path(__file__).resolve().parents[2]
ORIGINAL=ROOT/'data/quality/disagreement-live/original/database.json'

def original_request(boundary):
    data=json.loads(ORIGINAL.read_text(encoding='utf-8'));d=data['discussions'][0]
    return ModelRequest(task='insights',discussion_id=d['id'],run_id=d['current_run_id'],topic=d['topic'],
        expert_count=d['expert_count'],participants=[{k:r[k] for k in Participant.model_fields} for r in data['participants']],
        messages=[{k:r[k] for k in Message.model_fields} for r in sorted(data['messages'],key=lambda r:r['turn_no']) if r['turn_no']<=boundary],
        through_turn=boundary,insight_version=1)

def opposite_point(req):
    return dict(kind='disagreement',content='赵启主张把就业质量恶化计入广义失业，林禾主张归入劳动市场恶化而不统称失业。',
        source_turns=[9,10],evidence=[dict(turn=t,quote=req.messages[t-1].content) for t in (9,10)])

def test_original_opposed_judgments_survive_without_joint_support_of_each_side():
    req=original_request(10);point=opposite_point(req)
    output={'reviews':[dict(index=0,kind='disagreement',content=point['content'],source_turns=[9,10],evidence=point['evidence'],
        checks=checks(every_condition_supported=False,opposing_judgments_supported=True))]}
    result=bind_result(req,reviewed_points(req,{'items':[point]},json.dumps(output,ensure_ascii=False)))
    assert len(result.items)==1 and result.items[0].kind=='disagreement'
    assert result.items[0].source_message_ids==tuple(req.messages[t-1].id for t in (9,10))

@pytest.mark.parametrize('reason',['supplement','different_focus','unanswered','withdrawn'])
def test_unopposed_or_resolved_candidates_are_not_disagreements(reason):
    req=original_request(12);point=opposite_point(req)
    cases={'supplement':('我支持单列记录。','我也支持单列记录，还建议增加复查。'),
        'different_focus':('我关注维护费用。','我关注读者便利。'),
        'unanswered':('还需要查阅资料，暂不判断。','我也暂未形成判断。')}
    if reason in cases:
        a,b=cases[reason];messages=list(req.messages)
        messages[8]=messages[8].model_copy(update={'content':a})
        messages[9]=messages[9].model_copy(update={'content':b})
        req=req.model_copy(update={'messages':tuple(messages)});point=opposite_point(req)
    output={'reviews':[dict(index=0,kind='disagreement',content=point['content'],source_turns=[9,10],evidence=point['evidence'],
        checks=checks(opposing_judgments_supported=reason=='withdrawn',not_superseded=reason!='withdrawn'))]}
    result=bind_result(req,reviewed_points(req,{'items':[point]},json.dumps(output,ensure_ascii=False)))
    assert result.items==()

def test_consensus_still_requires_joint_support_even_when_opposition_flag_is_true():
    req=original_request(10);point=opposite_point(req)|{'kind':'consensus'}
    output={'reviews':[dict(index=0,content=point['content'],source_turns=[9,10],
        checks=checks(every_condition_supported=False,opposing_judgments_supported=True))]}
    assert bind_result(req,reviewed_points(req,{'items':[point]},json.dumps(output,ensure_ascii=False))).items==()


def test_kind_specific_review_can_keep_partial_consensus_and_other_disagreement():
    req=original_request(10);opposed=opposite_point(req)
    common=dict(kind='consensus',content='林禾与孙敏认可区分局部冲击与净失业。',source_turns=[2,3],
        evidence=[dict(turn=t,quote=req.messages[t-1].content) for t in (2,3)])
    candidate={'items':[common,opposed]}
    output={'reviews':[dict(index=i,kind=p['kind'],content=p['content'],source_turns=p['source_turns'],evidence=p['evidence'],
        checks=checks() if i==0 else checks(every_condition_supported=False,opposing_judgments_supported=True)) for i,p in enumerate(candidate['items'])]}
    result=bind_result(req,reviewed_points(req,candidate,json.dumps(output,ensure_ascii=False)))
    assert [p.kind for p in result.items]==['consensus','disagreement']

def test_original_prefix10_http_draft_and_review_keep_conflict_prefix12_removes_it():
    req10=original_request(10);req12=original_request(12);point=opposite_point(req10);seen=[]
    def upstream(http_request):
        body=json.loads(http_request.content);ctx=json.loads(body['messages'][1]['content']);seen.append(ctx)
        if 'candidate' not in ctx:return httpx.Response(200,json=answer({'items':[point]}))
        resolved=ctx['through_turn']==12
        assert 'opposing_judgments_supported' in body['messages'][0]['content']
        output={'reviews':[dict(index=0,kind='disagreement',content=point['content'],source_turns=[9,10],evidence=point['evidence'],
            checks=checks(every_condition_supported=False,opposing_judgments_supported=True,not_superseded=not resolved))]}
        return httpx.Response(200,json=answer(output))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            conflict=await gateway.generate(req10);resolved=await gateway.generate(req12)
        assert len(conflict.items)==1 and resolved.items==()
        assert seen[1]['through_turn']==10 and len(seen[1]['messages'])==10
        assert seen[3]['messages'][10]['content']==req12.messages[10].content
    asyncio.run(run())


def test_direct_expert_rebuttal_triggers_odd_boundary_without_waiting_for_next_pair(setup):
    from backend.app.engine import DiscussionEngine
    from backend.app.contracts import IntentResult
    from backend.app.model_gateway import DeterministicModelGateway
    client,repo,did,rid=prepared(setup)
    # Existing three formal messages: the next reply would be even; add one first.
    statement(repo,did,rid,2);context=repo.begin_cycle(did,rid)
    actor=next(p.id for p in context.snapshot.participants if p.kind=='EXPERT' and p.id!=context.snapshot.messages[-1].participant_id)
    target=context.snapshot.messages[-1].id
    repo.record_intents(context,{actor:IntentResult(task='intent',kind='REBUT',target_message_id=target,relevance=90,public_focus='不同判断')})
    async def run():
        import time
        supervisor=TaskSupervisor(repo,client.app.state.tasks.settings,lambda:DeterministicModelGateway())
        requests=[]
        supervisor.request_insights=lambda did,rid,boundary,**kwargs:requests.append((boundary,kwargs))
        engine=DiscussionEngine(supervisor);engine.deadline=time.monotonic()+2
        assert await engine.speak(context,actor,participation_kind='REBUT',target_message_id=target)
        assert requests==[(5,{'priority':True})]
    asyncio.run(run())


def test_two_discussions_drain_independently_and_cancelled_late_output_cannot_publish(setup):
    from backend.tests.test_start_recovery import ready
    from backend.tests.test_turn_transactions import opening
    from backend.app.contracts import StartDiscussion
    client,repo,a,ra=prepared(setup)
    bid,_=ready(client);b=UUID(bid)
    rb=UUID(repo.start(b,StartDiscussion(roster_revision=1),uuid4(),client.app.state.tasks.settings).body['run_id'])
    opening(repo,b,rb);statement(repo,b,rb,0);statement(repo,b,rb,1)
    async def run():
        class Gateway:
            def __init__(self):self.gates={ra:asyncio.Event(),rb:asyncio.Event()};self.entered=asyncio.Event();self.started=set()
            async def generate(self,req):
                self.started.add(req.run_id)
                if len(self.started)==2:self.entered.set()
                try:await self.gates[req.run_id].wait()
                except asyncio.CancelledError:pass  # Deliberately noncooperative provider.
                return evidence(req,'disagreement')
        gateway=Gateway();supervisor=TaskSupervisor(repo,client.app.state.tasks.settings,lambda:gateway)
        supervisor.request_insights(a,ra,3);supervisor.request_insights(b,rb,3)
        await gateway.entered.wait();gateway.gates[ra].set()
        await supervisor.insight_tasks[str(ra)]
        assert repo.snapshot(a).insights.through_turn==3 and repo.snapshot(b).insights.version==0
        await supervisor.cancel_insights(rb);repo.fail_run(b,rb,'TASK_FAILED')
        assert repo.snapshot(b).insights.version==0
        assert not any(e['type']=='insights.updated' for e in events(client,str(b)))
        assert repo.snapshot(a).insights.items and not supervisor.insight_tasks
    asyncio.run(run())


def test_end_wait_uses_original_finite_extraction_budget_then_final_can_succeed(setup):
    client,repo,did,rid=prepared(setup)
    async def run():
        settings=client.app.state.tasks.settings.model_copy(update={'insight_max_seconds':1,'model_max_attempts':1})
        gateway=BoundaryGateway();supervisor=TaskSupervisor(repo,settings,lambda:gateway)
        supervisor.request_insights(did,rid,3);await gateway.started.wait()
        statement(repo,did,rid,2);repo.finish_run(did,rid,'host_end')
        await asyncio.wait_for(supervisor.finalize_insights(did,rid),timeout=3)
        assert repo.snapshot(did).insights.through_turn==4
        with repo.database.connect() as conn:
            jobs=[tuple(r) for r in conn.execute('SELECT through_turn,state,error_code FROM insight_jobs WHERE discussion_id=? ORDER BY version',(str(did),))]
        assert jobs==[(3,'FAILED','MODEL_TIMEOUT'),(4,'SUCCEEDED',None)]
        assert len(gateway.calls)==2 and not supervisor.insight_tasks
    asyncio.run(run())
class BoundaryGateway:
    def __init__(self):self.calls=[];self.release=asyncio.Event();self.started=asyncio.Event();self.cancelled=False
    async def generate(self,req):
        self.calls.append(req)
        if len(self.calls)==1:
            self.started.set()
            try:await self.release.wait()
            except asyncio.CancelledError:self.cancelled=True;raise
        raw=evidence(req,'disagreement')
        return raw

def test_end_drains_inflight_process_result_before_final_prefix(setup):
    client,repo,did,rid=prepared(setup)
    async def run():
        gateway=BoundaryGateway();supervisor=TaskSupervisor(repo,client.app.state.tasks.settings,lambda:gateway)
        supervisor.request_insights(did,rid,3);await gateway.started.wait()
        statement(repo,did,rid,2);repo.finish_run(did,rid,'host_end')
        final=asyncio.create_task(supervisor.finalize_insights(did,rid))
        await asyncio.sleep(.03)
        try:
            assert not gateway.cancelled
            assert repo.snapshot(did).insight_status.through_turn==3
        finally:gateway.release.set();await final
        assert [r.through_turn for r in gateway.calls]==[3,4]
        updates=[e['payload'] for e in events(client,str(did)) if e['type']=='insights.updated']
        assert [e['through_turn'] for e in updates]==[3,4]
        assert len(updates[0]['items'])==1 and repo.snapshot(did).insights.through_turn==4
        assert repo.claim_insights(did,rid,3) is None
        assert not supervisor.insight_tasks and not supervisor.insight_targets
    asyncio.run(run())

def test_one_priority_reply_prefix_is_not_coalesced_away_by_normal_updates(setup):
    client,repo,did,rid=prepared(setup)
    async def run():
        gateway=BoundaryGateway();supervisor=TaskSupervisor(repo,client.app.state.tasks.settings,lambda:gateway)
        supervisor.request_insights(did,rid,2);await gateway.started.wait()
        try:
            supervisor.request_insights(did,rid,3,priority=True)
            statement(repo,did,rid,2)
            supervisor.request_insights(did,rid,4)
            assert len(supervisor.insight_tasks)==len(supervisor.insight_targets)==1
            assert supervisor.insight_targets[str(rid)]==3
        finally:gateway.release.set();await supervisor.insight_tasks[str(rid)]
        assert [r.through_turn for r in gateway.calls]==[2,3]
        repo.finish_run(did,rid,'host_end');await supervisor.finalize_insights(did,rid)
        assert [r.through_turn for r in gateway.calls]==[2,3,4]
        assert repo.snapshot(did).insights.through_turn==4
    asyncio.run(run())

def test_process_and_final_batches_can_represent_resolution_without_replaying_messages(setup):
    client,repo,did,rid=prepared(setup);first=repo.claim_insights(did,rid)
    raw=evidence(first.request,'disagreement');common=evidence(first.request)['items'][0]
    raw['items'].append(common)
    assert repo.complete_insights(first,raw)
    assert {i.kind for i in repo.snapshot(did).insights.items}=={'consensus','disagreement'}
    statement(repo,did,rid,2);repo.finish_run(did,rid,'host_end')
    last=repo.claim_insights(did,rid);assert repo.complete_insights(last,evidence(last.request))
    assert repo.complete_insights(first,raw) is False
    assert {i.kind for i in repo.snapshot(did).insights.items}=={'consensus'}
    assert len(repo.snapshot(did).messages)==4

def test_summary_does_not_treat_a_stale_process_batch_as_final_evidence(setup):
    client,repo,did,rid=prepared(setup);process=repo.claim_insights(did,rid)
    assert repo.complete_insights(process,evidence(process.request,'disagreement'))
    statement(repo,did,rid,2);repo.finish_run(did,rid,'host_end')
    final=repo.claim_insights(did,rid);repo.fail_insights(final,'MODEL_TIMEOUT')
    summary=repo.claim_summary(did,rid)
    assert summary.request.through_turn==4 and len(summary.request.messages)==4
    assert summary.request.insights.items==()
    assert repo.snapshot(did).insights.items  # UI retains process evidence with its boundary.
