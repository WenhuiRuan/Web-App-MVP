"""Stage6A acceptance: continuity is reviewed evidence, never unconditional union."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from backend.app.contracts import InsightBatch, ModelRequest, Snapshot
from backend.app.deepseek_gateway import DeepSeekGateway, bind_result, reviewed_points, reviewed_summary
from backend.app.model_gateway import InvalidModelResult
from backend.tests.test_deepseek import request, config, answer, checks, summary_review
from backend.tests.test_insight_pipeline import prepared, statement, evidence
from backend.tests.test_roster_tasks import setup


def library():
    root = Path(__file__).resolve().parents[2]
    snap = Snapshot.model_validate(json.loads((root/'data/quality/stage6a-revision/complete-browser.json').read_text(encoding='utf-8'))['snapshot'])
    d = snap.discussion
    return ModelRequest(task='insights', discussion_id=d.id, run_id=d.run_id, topic=d.topic,
        expert_count=d.expert_count, participants=snap.participants, messages=snap.messages,
        through_turn=len(snap.messages), insight_version=7)


def library_point(req):
    return {'kind':'consensus','content':'沈知微与郑书言共同建议记录老年读者使用率和人工求助次数，用于判断是否调整时段。',
        'source_turns':[4,6], 'evidence':[{'turn':t,'quote':req.messages[t-1].content} for t in (4,6)]}


def test_next_sqlite_claim_contains_previous_committed_evidence(setup):
    _, repo, did, rid = prepared(setup)
    first = repo.claim_insights(did,rid)
    assert repo.complete_insights(first,evidence(first.request))
    previous = repo.snapshot(did).insights
    statement(repo,did,rid,2)
    next_claim=repo.claim_insights(did,rid)
    assert next_claim.request.insights == previous


def test_prior_evidence_is_allowed_only_with_older_version_and_scoped_sources():
    req=library()
    result=bind_result(req,json.dumps({'items':[library_point(req)]},ensure_ascii=False))
    prior=InsightBatch(version=3,through_turn=6,items=result.items)
    valid=ModelRequest.model_validate(req.model_dump()|{'insights':prior})
    assert valid.insights == prior
    for bad in [prior.model_copy(update={'version':7}),prior.model_copy(update={'through_turn':12}),
        prior.model_copy(update={'items':(prior.items[0].model_copy(update={'source_message_ids':(uuid4(),)}),)})]:
        with pytest.raises(ValidationError): ModelRequest.model_validate(req.model_dump()|{'insights':bad})


def test_library_intersection_survives_draft_omission_but_withdrawal_removes_it():
    req=library(); point=library_point(req)
    prior=InsightBatch(version=3,through_turn=6,items=bind_result(req,json.dumps({'items':[point]},ensure_ascii=False)).items)
    req=req.model_copy(update={'insights':prior})
    async def run():
        for withdrawn in (False,True):
            current=req
            if withdrawn:
                last=req.messages[-1].model_copy(update={'participant_id':req.messages[3].participant_id,
                    'content':'我撤回记录人工求助次数来调整时段的建议，不再支持这项共同主张。'})
                current=req.model_copy(update={'messages':(*req.messages[:-1],last)})
            def upstream(http_request):
                context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
                if 'candidate' not in context:
                    assert context['previous_through_turn']==6
                    return httpx.Response(200,json=answer({'items':[]}))
                assert len(context['candidate']['items'])==1
                assert context['candidate']['items'][0]['source_turns']==[4,6]
                output={'reviews':[{'index':0,'source_turns':[4,6], 'content':point['content'],
                    'checks':checks(not_superseded=not withdrawn)}]}
                return httpx.Response(200,json=answer(output))
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
                result=await DeepSeekGateway(config(),client=client).generate(current)
                assert len(result.items)==(0 if withdrawn else 1)
    asyncio.run(run())


def test_review_can_requote_same_sources_to_narrow_a_polluted_candidate():
    req=library(); point=library_point(req)
    # Draft quote from 6 contains the later single-party staffing detail, missing its
    # earlier shared metric claim. Review must be able to select the actual shared part.
    polluted=dict(point,content=point['content']+'且保留视频协助。',evidence=[
        point['evidence'][0],{'turn':6,'quote':req.messages[5].content[-20:]}])
    review={'reviews':[{'index':0,'source_turns':[4,6],'content':point['content'],
        'checks':checks(not_superseded=True),'evidence':point['evidence']}]}
    result=bind_result(req,reviewed_points(req,{'items':[polluted]},json.dumps(review,ensure_ascii=False)))
    assert result.items[0].content==point['content']
    review['reviews'][0]['evidence'][0]['quote']='从未发表的观点'
    with pytest.raises(InvalidModelResult):
        bind_result(req,reviewed_points(req,{'items':[polluted]},json.dumps(review,ensure_ascii=False)))


def test_plain_proposal_cannot_be_classified_as_an_unanswered_question():
    req=request('summary')
    reviewed=summary_review(pending=[{'turn':2,'quote':req.messages[1].content,'issue':'UNANSWERED_QUESTION'}])
    with pytest.raises(InvalidModelResult): reviewed_summary(req,json.dumps(reviewed,ensure_ascii=False))


def test_omitted_redundant_positions_do_not_claim_no_proposal_was_made():
    req=library().model_copy(update={'task':'summary','insight_version':None})
    point=bind_result(library(),json.dumps({'items':[library_point(req)]},ensure_ascii=False)).items
    req=req.model_copy(update={'insights':InsightBatch(version=7,through_turn=11,items=point)})
    body=json.loads(reviewed_summary(req,json.dumps(summary_review(consensus_indices=[0]),ensure_ascii=False)))['content']
    assert '尚无专家明确提出方案' not in body
    assert '待澄清：' not in body
    assert point[0].content in body


def test_summary_does_not_repeat_a_proposal_as_pending_or_duplicate_positions():
    req=request('summary'); text=req.messages[1].content
    position={'speaker_slot':1,'source_turns':[2],'content':text}
    reviewed=summary_review(positions=[position,position],pending=[{'turn':2,'quote':text,'issue':'UNVERIFIED_PROPOSAL'}])
    result=json.loads(reviewed_summary(req,json.dumps(reviewed,ensure_ascii=False)))['content']
    assert result.count(text)==1


def test_review_deduplicates_the_same_repaired_claim_with_reordered_sources():
    req=library(); point=library_point(req)
    candidate={'items':[point,dict(point,content=point['content']+'另有单方条件。')]}
    output={'reviews':[dict(index=i,source_turns=[4,6] if i==0 else [6,4],content=point['content'],
        checks=checks(not_superseded=True)) for i in range(2)]}
    result=bind_result(req,reviewed_points(req,candidate,json.dumps(output,ensure_ascii=False)))
    assert len(result.items)==1


def test_summary_review_rejects_a_long_transcript_listing():
    req=request('summary'); text=req.messages[1].content
    position={'speaker_slot':1,'source_turns':[2],'content':text}
    with pytest.raises(InvalidModelResult):
        reviewed_summary(req,json.dumps(summary_review(positions=[position]*4),ensure_ascii=False))


def test_rejected_candidate_may_omit_its_content_without_losing_other_points():
    req=library(); point=library_point(req)
    output={'reviews':[dict(index=0,source_turns=[],content='',checks=checks(explicit_positions=False,not_superseded=True)),
        dict(index=1,source_turns=[4,6],content=point['content'],checks=checks(not_superseded=True))]}
    result=bind_result(req,reviewed_points(req,{'items':[point,point]},json.dumps(output,ensure_ascii=False)))
    assert len(result.items)==1


def test_one_unsupported_numeric_candidate_does_not_discard_valid_intersection():
    req=library(); point=library_point(req)
    bad=dict(point,content=point['content']+'且每周轮值不超过一次。')
    output={'reviews':[dict(index=i,source_turns=[4,6],content=p['content'],checks=checks(not_superseded=True))
        for i,p in enumerate([bad,point])]}
    result=bind_result(req,reviewed_points(req,{'items':[bad,point]},json.dumps(output,ensure_ascii=False)))
    assert len(result.items)==1 and result.items[0].content==point['content']


def test_draft_bad_quote_does_not_block_review_of_a_valid_candidate():
    req=library(); point=library_point(req)
    bad=dict(point,evidence=[{'turn':4,'quote':'未发表的句子'},{'turn':6,'quote':req.messages[5].content}])
    async def run():
        def upstream(http_request):
            context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
            if 'candidate' not in context: return httpx.Response(200,json=answer({'items':[bad,point]}))
            assert context['candidate']['items']==[point]
            return httpx.Response(200,json=answer({'reviews':[dict(index=0,source_turns=[4,6],content=point['content'],checks=checks(not_superseded=True))]}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            assert len((await DeepSeekGateway(config(),client=client).generate(req)).items)==1
    asyncio.run(run())


def test_summary_allows_actual_interrogative_without_question_mark_and_avoids_substring_repeat():
    req=request('summary'); line='采集由谁负责，使用哪张表记录。'
    req=req.model_copy(update={'messages':(req.messages[0].model_copy(update={'content':line}),*req.messages[1:])})
    output=summary_review(pending=[{'turn':1,'quote':line,'issue':'UNANSWERED_QUESTION'}])
    assert line in json.loads(reviewed_summary(req,json.dumps(output,ensure_ascii=False)))['content']
    text=req.messages[1].content
    output=summary_review(positions=[dict(speaker_slot=1,source_turns=[2],content=text)],
        pending=[dict(turn=2,quote='执行成本需要单独验证',issue='UNVERIFIED_PROPOSAL')])
    assert json.loads(reviewed_summary(req,json.dumps(output,ensure_ascii=False)))['content'].count('执行成本需要单独验证')==1


def test_each_candidate_review_focuses_on_its_sources_and_later_supporter_statements():
    req=library(); a=library_point(req)
    b=dict(kind='consensus',content='郑书言与周敏行共同建议比较上午自助下午人工安排。',source_turns=[2,3],
        evidence=[dict(turn=t,quote=req.messages[t-1].content) for t in (2,3)])
    async def run():
        def upstream(http_request):
            context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
            if 'candidate' not in context: return httpx.Response(200,json=answer({'items':[a,b]}))
            assert len(context['candidate']['items'])==1
            point=context['candidate']['items'][0]
            if point['source_turns']==[4,6]:
                assert {m['turn'] for m in context['messages']}=={4,6,9}
            return httpx.Response(200,json=answer({'reviews':[dict(index=0,source_turns=point['source_turns'],content=point['content'],checks=checks(not_superseded=True))]}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
            assert len(result.items)==2 and len({p.id for p in result.items})==2
    asyncio.run(run())


def test_review_can_correct_candidate_kind_when_sources_support_a_common_claim():
    req=library(); point=library_point(req)
    output={'reviews':[dict(index=0,kind='consensus',source_turns=[4,6],content=point['content'],checks=checks(not_superseded=True))]}
    result=bind_result(req,reviewed_points(req,{'items':[dict(point,kind='disagreement')]},json.dumps(output,ensure_ascii=False)))
    assert result.items[0].kind=='consensus'


def test_summary_cannot_silently_claim_empty_when_latest_insight_is_omitted():
    req=library(); point=library_point(req)
    points=bind_result(req,json.dumps({'items':[point]},ensure_ascii=False))
    req=req.model_copy(update={'task':'summary','insight_version':None,
        'actor_id':req.participants[0].id,'insights':InsightBatch(version=7,through_turn=11,items=points.items)})
    with pytest.raises(InvalidModelResult): reviewed_summary(req,json.dumps(summary_review(),ensure_ascii=False))


def test_supplement_without_explicit_opposition_is_not_published_as_disagreement():
    req=library()
    point=dict(kind='disagreement',content='周敏行与郑书言对巡检是否由志愿者承担存在互斥立场。',source_turns=[3,6],
        evidence=[dict(turn=t,quote=req.messages[t-1].content) for t in (3,6)])
    output={'reviews':[dict(index=0,source_turns=[3,6],content=point['content'],checks=checks(not_superseded=True))]}
    assert bind_result(req,reviewed_points(req,{'items':[point]},json.dumps(output,ensure_ascii=False))).items==()


def test_selection_question_does_not_support_a_joint_recording_consensus():
    req=library()
    point=dict(kind='consensus',content='高远舟与沈知微共同建议同时记录门禁告警次数与盘点差额。',source_turns=[8,9],
        evidence=[dict(turn=t,quote=req.messages[t-1].content) for t in (8,9)])
    output={'reviews':[dict(index=0,source_turns=[8,9],content=point['content'],checks=checks(not_superseded=True))]}
    assert bind_result(req,reviewed_points(req,{'items':[point]},json.dumps(output,ensure_ascii=False))).items==()


def test_same_exact_evidence_does_not_repeat_rephrased_claim():
    req=library(); p=library_point(req)
    output={'reviews':[dict(index=i,source_turns=[4,6],evidence=p['evidence'],
        content=p['content'] if i==0 else '双方共同建议统计这两项指标，用来判断是否调整时段。',checks=checks(not_superseded=True)) for i in (0,1)]}
    result=bind_result(req,reviewed_points(req,{'items':[p,p]},json.dumps(output,ensure_ascii=False)))
    assert len(result.items)==1
