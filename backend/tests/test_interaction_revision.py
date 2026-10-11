import asyncio
import json
from pathlib import Path

from backend.app.contracts import Snapshot, IntentResult
from backend.app.scheduling import choose_speaker
from backend.tests.test_discussion_engine import ControlledGateway, start_ready
from backend.tests.test_roster_tasks import wait_for
from backend.app.main import create_app
from backend.app.config import Settings
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_original_direct_rebuttal_is_not_delayed_for_equal_appearances():
    original = json.loads((ROOT/'data/quality/stage6c-interaction/original/database.json').read_text(encoding='utf-8'))
    snapshot = Snapshot.model_validate(json.loads((ROOT/'data/quality/stage6c-interaction/original/snapshot.json').read_text(encoding='utf-8')))
    prefix = snapshot.model_copy(update={'messages': snapshot.messages[:3]})
    candidates = {r['participant_id']: r for r in original['speaking_intents'] if r['cycle']==4}
    intents = {next(p.id for p in snapshot.participants if str(p.id)==actor):IntentResult.model_validate(
        {k:row[k] for k in ('kind','target_message_id','relevance','public_focus')}|{'task':'intent'}) for actor,row in candidates.items()}
    chosen = choose_speaker(prefix,intents)
    assert next(p.name for p in snapshot.participants if p.id==chosen)=='孙哲'


class InteractionGateway(ControlledGateway):
    async def generate(self, request):
        if request.task=='host_control':
            self.requests.append(request)
            return {'task':'host_control','action':'followup' if len(request.messages)==2 else 'continue',
                    'public_focus':'请说明这个数量的依据；尚无依据时应承认它只是建议。'}
        if request.task=='insights':
            self.requests.append(request)
            while not self.release_insights.is_set(): await asyncio.sleep(.005)
            return {'task':'insights','items':[]}
        return await super().generate(request)


def test_content_followup_really_speaks_before_expert_candidates(tmp_path):
    import threading
    gateway=InteractionGateway(); gateway.release_insights=threading.Event(); gateway.release_insights.set()
    settings=Settings(_env_file=None,database_path=tmp_path/'host.sqlite3',discussion_max_turns=4,model_timeout_seconds=1)
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=gateway
        did,_=start_ready(client)
        snapshot=wait_for(client,did,'SUMMARIZING')
        assert [m['kind'] for m in snapshot['messages']]==['opening','statement','followup','statement']
        assert any(r.host_task=='followup' for r in gateway.requests if r.task=='utterance')


def test_slow_insight_does_not_block_later_formal_messages(tmp_path):
    import threading
    gateway=InteractionGateway(); gateway.release_insights=threading.Event()
    settings=Settings(_env_file=None,database_path=tmp_path/'parallel.sqlite3',discussion_max_turns=6,model_timeout_seconds=1)
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=gateway
        try:
            did,_=start_ready(client)
            snapshot=wait_for(client,did,'SUMMARIZING',timeout=2)
            assert len(snapshot['messages'])==6
            assert any(r.task=='insights' for r in gateway.requests)
            assert len(client.app.state.tasks.insight_tasks)==1
        finally:
            gateway.release_insights.set(); gateway.summary_release.set()


def original_request(task='insights'):
    from backend.app.contracts import ModelRequest
    snap=Snapshot.model_validate(json.loads((ROOT/'data/quality/stage6c-interaction/original/snapshot.json').read_text(encoding='utf-8')))
    d=snap.discussion
    return ModelRequest(task=task,discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,
        roster_revision=d.roster_revision,participants=snap.participants,messages=snap.messages,
        actor_id=next(p.id for p in snap.participants if p.kind=='HOST') if task=='summary' else None,
        through_turn=len(snap.messages),insight_version=5 if task=='insights' else None)


def test_same_sources_can_support_distinct_claims():
    from backend.app.deepseek_gateway import distinct_evidence
    evidence=[{'turn':2,'quote':'支持登记和公示'},{'turn':5,'quote':'支持登记和公示'}]
    points=[{'kind':'consensus','content':text,'source_turns':[2,5],'evidence':evidence} for text in ('共同登记','共同公示')]
    assert len(distinct_evidence(points))==2


def test_semantic_merge_explicitly_unions_sources_and_keeps_other_claims():
    from backend.app.deepseek_gateway import reviewed_points,bind_result
    from backend.tests.test_deepseek import checks
    req=original_request()
    candidate={'items':[{'kind':'consensus','content':text,'source_turns':turns,
        'evidence':[{'turn':t,'quote':req.messages[t-1].content} for t in turns]} for text,turns in
        [('共同登记并公示',[2,5]),('共同公示登记投喂点',[2,5]),('共同建议绝育后优先领养',[3,6]),('优先领养的共同建议',[3,4])]]}
    reviews=[dict(index=0,checks=checks(),content='孙哲与李岩共同建议登记并公示投喂点。',source_turns=[2,5],merge_with=[1]),
        dict(index=1,checks=checks(explicit_positions=False),content='',source_turns=[]),
        dict(index=2,checks=checks(),content='周宁与孙哲及吴桐共同建议绝育后优先领养，仍为提案。',source_turns=[3,4,6],merge_with=[3]),
        dict(index=3,checks=checks(explicit_positions=False),content='',source_turns=[])]
    result=bind_result(req,reviewed_points(req,candidate,json.dumps({'reviews':reviews},ensure_ascii=False)))
    assert len(result.items)==2
    assert set(result.items[1].source_message_ids)=={req.messages[t-1].id for t in (3,4,6)}


def test_unresolved_condition_survives_partial_agreement_without_false_footer():
    from backend.app.deepseek_gateway import reviewed_summary
    from backend.tests.test_deepseek import summary_review
    req=original_request('summary')
    output=summary_review(introduction='投喂与领养可以衔接，但转介保障尚未说明。',pending=[
        {'turn':7,'quote':'不设收容转介比例下限和领养成功率公示，收容出口仍会被边缘化','issue':'UNRESOLVED_CONDITION'}])
    result=json.loads(reviewed_summary(req,json.dumps(output,ensure_ascii=False)))['content']
    assert '收容出口仍会被边缘化' in result
    assert '尚无充分证据表明已发生明确分歧' not in result


def test_parallel_runs_coalesce_to_final_prefix_and_shutdown_drains(tmp_path):
    import threading
    gateway=InteractionGateway();gateway.release_insights=threading.Event()
    settings=Settings(_env_file=None,database_path=tmp_path/'isolated.sqlite3',discussion_max_turns=8,model_timeout_seconds=5)
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=gateway
        a,_=start_ready(client);b,_=start_ready(client)
        sa=wait_for(client,a,'SUMMARIZING');sb=wait_for(client,b,'SUMMARIZING')
        assert len(sa['messages'])==len(sb['messages'])==8
        assert len(client.app.state.tasks.insight_tasks)==2
        gateway.release_insights.set()
        import time
        until=time.monotonic()+3
        while time.monotonic()<until:
            sa=client.get(f'/api/discussions/{a}').json();sb=client.get(f'/api/discussions/{b}').json()
            if sa['insights']['through_turn']==sb['insights']['through_turn']==8:break
            time.sleep(.01)
        assert sa['insights']['through_turn']==sb['insights']['through_turn']==8
        for did in (a,b):
            boundaries=[r.through_turn for r in gateway.requests if r.task=='insights' and str(r.discussion_id)==did]
            assert boundaries==sorted(set(boundaries))
            assert len(boundaries)<=3 and boundaries[-1]==8
            assert all(str(m.discussion_id)==did for r in gateway.requests if str(r.discussion_id)==did for m in r.messages)
    assert not client.app.state.tasks.insight_tasks
    assert not client.app.state.tasks.insight_targets


def test_shutdown_cancels_blocked_extraction_and_marks_interrupted(tmp_path):
    import threading
    from backend.app.synthesis_repository import SynthesisRepository
    gateway=InteractionGateway();gateway.release_insights=threading.Event()
    settings=Settings(_env_file=None,database_path=tmp_path/'cancel.sqlite3',discussion_max_turns=6,model_timeout_seconds=5)
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=gateway
        did,_=start_ready(client);wait_for(client,did,'SUMMARIZING')
    snapshot=client.app.state.tasks.repository.snapshot(did)
    assert snapshot.insight_status.state=='INTERRUPTED'
    assert not client.app.state.tasks.insight_tasks


def test_host_control_targets_are_bound_to_current_roster_and_messages():
    from backend.app.model_gateway import validate_result,InvalidModelResult
    import pytest
    from uuid import uuid4
    req=original_request('summary').model_copy(update={'task':'host_control','through_turn':None,'cycle':9})
    target=req.messages[6].id;expert=req.messages[6].participant_id
    good={'task':'host_control','action':'followup','public_focus':'请说明保障条件。',
          'addressed_actor_id':expert,'target_message_id':target}
    assert validate_result(req,good).addressed_actor_id==expert
    for field in ('addressed_actor_id','target_message_id'):
        with pytest.raises(InvalidModelResult): validate_result(req,good|{field:uuid4()})


def test_run_failure_cancels_extraction_and_marks_job_failed(tmp_path):
    import threading
    from backend.app.model_gateway import ModelServiceError
    class Failing(InteractionGateway):
        async def generate(self,request):
            if request.task=='utterance' and len(request.messages)>=2:
                raise ModelServiceError('MODEL_AUTH_FAILED')
            return await super().generate(request)
    gateway=Failing();gateway.release_insights=threading.Event()
    settings=Settings(_env_file=None,database_path=tmp_path/'failure.sqlite3',discussion_max_turns=8,model_timeout_seconds=5)
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=gateway
        did,_=start_ready(client);snapshot=wait_for(client,did,'FAILED')
        assert snapshot['insight_status']['state']=='FAILED'
        assert snapshot['insight_status']['error_code']=='MODEL_AUTH_FAILED'
        assert not client.app.state.tasks.insight_tasks


def test_batch_review_input_has_explicit_candidate_indices():
    import asyncio,httpx
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.tests.test_deepseek import config,answer,checks
    req=original_request()
    def upstream(http_request):
        context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
        if 'candidate' not in context:
            return httpx.Response(200,json=answer({'items':[{'kind':'consensus','content':'孙哲与李岩共同建议登记并公示投喂点。',
              'source_turns':[2,5],'evidence':[{'turn':t,'quote':req.messages[t-1].content} for t in (2,5)]}]}))
        assert [item['index'] for item in context['candidate']['items']]==[0]
        item=context['candidate']['items'][0]
        return httpx.Response(200,json=answer({'reviews':[dict(index=0,checks=checks(),content=item['content'],source_turns=item['source_turns'])]}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
            assert len(result.items)==1
    asyncio.run(run())


def test_merge_follower_cannot_belong_to_two_leaders():
    import pytest
    from backend.app.deepseek_gateway import reviewed_points
    from backend.app.model_gateway import InvalidModelResult
    from backend.tests.test_deepseek import checks
    req=original_request()
    point={'kind':'consensus','content':'登记并公示投喂点','source_turns':[2,5],
           'evidence':[{'turn':t,'quote':req.messages[t-1].content} for t in (2,5)]}
    output={'reviews':[dict(index=i,merge_with=[2],checks=checks(),content='孙哲与李岩共同建议登记并公示投喂点。',source_turns=[2,5]) for i in (0,1)]+[
        dict(index=2,checks=checks(explicit_positions=False),content='',source_turns=[])]}
    with pytest.raises(InvalidModelResult):reviewed_points(req,{'items':[point,point,point]},json.dumps(output,ensure_ascii=False))


def test_invalid_wire_candidate_does_not_discard_valid_independent_candidate():
    import asyncio,httpx
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.tests.test_deepseek import config,answer,checks
    req=original_request()
    point={'kind':'consensus','content':'孙哲与李岩共同建议登记并公示投喂点。','source_turns':[2,5],
           'evidence':[{'turn':t,'quote':req.messages[t-1].content} for t in (2,5)]}
    def upstream(http_request):
        context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
        if 'candidate' not in context:return httpx.Response(200,json=answer({'items':[point,dict(point,kind='divergence')]}))
        assert len(context['candidate']['items'])==1
        return httpx.Response(200,json=answer({'reviews':[dict(index=0,checks=checks(),content=point['content'],source_turns=[2,5])]}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            assert len((await gateway.generate(req)).items)==1
            assert gateway.metrics[0]['discarded_candidates']==1
    asyncio.run(run())


def test_partial_shared_candidate_gets_one_bounded_narrowing_review():
    import asyncio,httpx
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.tests.test_deepseek import config,answer,checks
    req=original_request();seen=[]
    point={'kind':'consensus','content':'共同登记并公示投喂点','source_turns':[2,5],
           'evidence':[{'turn':t,'quote':req.messages[t-1].content} for t in (2,5)]}
    def upstream(http_request):
        body=json.loads(http_request.content);context=json.loads(body['messages'][1]['content']);seen.append(context)
        if len(seen)==1:output={'items':[point]}
        elif len(seen)==2:output={'reviews':[dict(index=0,checks=checks(explicit_positions=False,every_condition_supported=False),content='',source_turns=[])]}
        else:output={'reviews':[dict(index=0,checks=checks(),content='孙哲与李岩共同建议公示投喂点，仍属提案。',source_turns=[2,5])]}
        return httpx.Response(200,json=answer(output))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            result=await gateway.generate(req)
            assert len(seen)==3
            assert len(result.items)==1 and '公示投喂点' in result.items[0].content
            assert [m['stage'] for m in gateway.metrics]==['draft','review','repair']
    asyncio.run(run())


def test_summary_context_exposes_insight_boundary_separately_from_frozen_messages():
    from backend.app.deepseek_gateway import public_context
    from backend.app.contracts import InsightBatch
    req=original_request('summary').model_copy(update={'insights':InsightBatch(version=2,through_turn=4)})
    context=public_context(req)
    assert context['through_turn']==8
    assert context['insights_through_turn']==4 and context['insights_version']==2


def test_summary_personal_quote_is_selected_from_authors_latest_message():
    import pytest
    from backend.app.deepseek_gateway import reviewed_summary
    from backend.app.model_gateway import InvalidModelResult
    from backend.tests.test_deepseek import summary_review
    req=original_request('summary')
    earlier=req.messages[1]; latest=req.messages[5]
    slot=next(i for i,p in enumerate(req.participants) if p.id==earlier.participant_id)
    def material(message):
        return json.dumps(summary_review(positions=[dict(speaker_slot=slot,source_turns=[message.turn_no],content=message.content[:100])]),ensure_ascii=False)
    with pytest.raises(InvalidModelResult): reviewed_summary(req,material(earlier))
    assert latest.content[:100] in json.loads(reviewed_summary(req,material(latest)))['content']
