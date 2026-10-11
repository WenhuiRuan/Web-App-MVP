"""Host guidance is an invitation, not an expert assignment (no paid calls)."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.deepseek_gateway import DeepSeekGateway
from backend.app.main import create_app
from backend.app.scheduling import choose_speaker
from backend.tests.test_deepseek import request, config, answer
from backend.tests.test_discussion_engine import ControlledGateway, start_ready
from backend.tests.test_roster_tasks import wait_for
from backend.tests.test_scheduling import panel, intent


@pytest.mark.parametrize('topic', [
    '你认为AI的飞速发展，在未来几年是否会造成大规模失业？',
    '城市中的流浪猫应该以定点投喂和绝育管理为主，还是逐步转向收容与领养？',
    '大学课堂应该禁止使用手机吗？',
    '公共图书馆是否应该延长夜间开放时间？',
])
def test_opening_asks_original_topic_and_invites_without_prefilled_angles(topic):
    req=request('utterance').model_copy(update={'topic':topic,'host_task':'opening','messages':(),
        'public_focus':'说明议题与讨论范围', 'attempt':2,'validation_feedback':'SENTENCE_COUNT'})
    def upstream(http_req):
        body=json.loads(http_req.content)
        context=json.loads(body['messages'][1]['content'])
        rules=context['opening_rules']
        assert rules['original_question']==topic and context['topic']==topic
        assert rules['preserve_topic_meaning'] and rules['invite_views']
        assert rules['allow_analysis_framework'] is False
        assert rules['assign_guest_directions'] is False
        assert 'background_max_sentences' not in rules and 'question_must_be_last' not in rules
        assert context['participants']==[{'slot':0,'kind':'HOST','name':req.participants[0].name,'title':req.participants[0].title}]
        assert context['actor_slot']==0 and context['host_task']=='opening'
        assert 'public_focus' not in context and 'messages' not in context
        assert 'stance' not in json.dumps(context,ensure_ascii=False)
        assert context['attempt']==2 and context['output_correction']['failure_type']=='SENTENCE_COUNT'
        system=body['messages'][0]['content']
        assert '不列讨论维度' in system and '自然的口语' in system
        assert '职业决定关注点' not in system and '先区分两种情况' not in system
        assert 'followup' not in system and 'linking' not in system
        # Controlled response checks transport and parsing, not actual model style.
        return httpx.Response(200,json=answer({'sentences':[rules['original_question'],'各位怎么看？']}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
        assert result.sentences==(topic,'各位怎么看？')
    asyncio.run(run())


def test_followup_keeps_actual_transcript_and_reference_without_opening_rules():
    req=request('utterance')
    target=req.messages[-1]
    req=req.model_copy(update={'host_task':'followup','host_reference_message_id':target.id,
        'addressed_actor_id':target.participant_id,'public_focus':'刚才的建议是否有依据？'})
    def upstream(http_req):
        body=json.loads(http_req.content);context=json.loads(body['messages'][1]['content'])
        assert 'opening_rules' not in context
        assert len(context['participants'])==len(req.participants)
        assert context['messages'][-1]['content']==target.content
        assert context['host_reference_message']['turn']==target.turn_no
        assert context['addressed_slot']==2
        assert context['public_focus']==req.public_focus
        assert 'followup基于已经出现的具体主张' in body['messages'][0]['content']
        return httpx.Response(200,json=answer({'sentences':['刚才提到执行成本需要验证，你愿意说明依据吗？']}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
        assert len(result.sentences)==1
    asyncio.run(run())


def test_mock_opening_does_not_install_a_discussion_framework():
    from backend.app.model_gateway import DeterministicModelGateway
    req=request('utterance').model_copy(update={'host_task':'opening','messages':()})
    result=asyncio.run(DeterministicModelGateway().generate(req))
    assert result.sentences==('今天这个议题，大家怎么看？',)


def test_actual_intent_http_context_marks_host_question_as_optional():
    req=request('intent').model_copy(update={'public_focus':'主持提示不能成为专家必须执行的分工'})
    captured=[]
    def upstream(http_req):
        context=json.loads(json.loads(http_req.content)['messages'][1]['content'])
        captured.append(context)
        rules=context['participation_rules']
        assert rules=={'host_question_is_invitation':True,'may_pass':True,'may_challenge_question':True,'must_follow_host_conclusion':False}
        assert context['participants'][context['actor_slot']]['stance']
        assert context['public_focus']=='' and context['focus_is_unverified'] is True
        return httpx.Response(200,json=answer({'kind':'PASS','target_turn':None,'relevance':0,'public_focus':'提问前提未形成依据，本轮没有新增内容。'}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
        assert result.kind=='PASS' and result.target_message_id is None
        assert len(captured)==1
    asyncio.run(run())


def test_named_pass_is_not_forced_and_other_expert_may_challenge(panel):
    named,other=panel.participants[1:3]
    host=panel.messages[0].model_copy(update={'kind':'followup','content':'这个方案是否必然有效？'})
    snap=panel.model_copy(update={'messages':(host,)})
    candidates={named.id:intent('PASS',0),other.id:intent('REBUT',80,host.id)}
    assert choose_speaker(snap,candidates,named.id)==other.id
    assert choose_speaker(snap,{named.id:intent('PASS',0)},named.id) is None
    # A name is a small response opportunity, not an unconditional ordering rule.
    assert choose_speaker(snap,{named.id:intent('SUPPLEMENT',10,host.id),other.id:intent('REBUT',90,host.id)},named.id)==other.id


def test_named_expert_can_pass_after_question_and_another_expert_responds(tmp_path):
    class InvitationGateway(ControlledGateway):
        def __init__(self):super().__init__();self.summary_release.set();self.named=None
        async def generate(self,req):
            if req.task=='host_control' and len(req.messages)==2:
                self.requests.append(req);self.named=next(p.id for p in req.participants if p.kind=='EXPERT')
                return {'task':'host_control','action':'followup','public_focus':'这个前提是否已经得到依据？',
                        'addressed_actor_id':self.named,'target_message_id':req.messages[-1].id}
            if req.task=='intent' and req.messages and req.messages[-1].kind=='followup':
                self.requests.append(req)
                if req.actor_id==self.named:
                    return {'task':'intent','kind':'PASS','relevance':0,'public_focus':'暂无新增依据。','target_message_id':None}
                return {'task':'intent','kind':'REBUT','relevance':90,'public_focus':'需要先质疑问题中尚未成立的前提。','target_message_id':req.messages[-1].id}
            return await super().generate(req)
    gateway=InvitationGateway()
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'panel.sqlite3',discussion_max_turns=4))) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        snap=wait_for(client,did,'COMPLETED')
        assert [m['kind'] for m in snap['messages']]==['opening','statement','followup','statement']
        expert_call=next(r for r in gateway.requests if r.task=='utterance' and len(r.messages)==3)
        assert expert_call.participation_kind=='REBUT' and str(expert_call.target_message_id)==snap['messages'][2]['id']
        assert snap['messages'][-1]['participant_id']!=str(gateway.named)
        assert all(r.public_focus=='' and r.host_task is None for r in gateway.requests if r.task=='intent')
        with client.app.state.database.connect() as conn:
            row=conn.execute('SELECT kind,target_message_id FROM speaking_intents WHERE discussion_id=? AND participant_id=? AND based_on_turn=3',(did,str(gateway.named))).fetchone()
            assert tuple(row)==('PASS',None)
