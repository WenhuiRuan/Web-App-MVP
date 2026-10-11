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
])
def test_opening_http_context_preserves_created_question_after_background(topic):
    req=request('utterance').model_copy(update={'topic':topic,'host_task':'opening','messages':()})
    def upstream(http_req):
        context=json.loads(json.loads(http_req.content)['messages'][1]['content'])
        rules=context['opening_rules']
        assert rules['original_question']==topic and context['topic']==topic
        assert rules['question_must_be_last'] and rules['background_max_sentences']==1
        assert rules['assign_guest_directions'] is False
        # Controlled response checks transport and parsing, not actual model style.
        return httpx.Response(200,json=answer({'sentences':['这个议题涉及多方影响，需要区分事实与判断。',rules['original_question']]}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
        assert len(result.sentences)==2 and result.sentences[-1]==topic
    asyncio.run(run())


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
