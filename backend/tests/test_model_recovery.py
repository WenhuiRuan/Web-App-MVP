"""No paid calls: safe diagnostics, correction feedback and bounded host recovery."""
import asyncio
import json
import time
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import UtteranceResult
from backend.app.deepseek_gateway import DeepSeekGateway
from backend.app.main import create_app
from backend.app.model_gateway import InvalidModelResult
from backend.tests.test_deepseek import request, config, answer
from backend.tests.test_discussion_engine import ControlledGateway, start_ready
from backend.tests.test_roster_tasks import wait_for


@pytest.mark.parametrize('text', ['他说：“成本仍需验证。”', '“短期冲击？”这个问题需要区分行业。',
    '增长1.5%不等于所有岗位下降。', '例如e.g.的缩写不代表句子结束。'])
def test_valid_sentence_boundaries(text):
    assert UtteranceResult(task='utterance', sentences=[text]).sentences == (text,)


@pytest.mark.parametrize('lines', [['第一句。', '第二句。'], ['问题是否已澄清？！'], ['成本仍需核对']])
def test_one_or_two_actual_sentences_remain_valid(lines):
    assert len(UtteranceResult(task='utterance',sentences=lines).sentences)==len(lines)


def test_quoted_terminal_is_preserved_in_formal_utterance():
    from backend.app.model_gateway import utterance_text
    text='他说：“成本仍需验证。”'
    result=UtteranceResult(task='utterance',sentences=[text])
    assert utterance_text(result)==text


@pytest.mark.parametrize('raw,kind', [
    ({'sentences':[]},'SENTENCE_COUNT'), ({'sentences':['一。二。']},'SENTENCE_BOUNDARY'),
    ({'sentences':['x'*201]},'SENTENCE_LENGTH'), ({'sentences':['']},'EMPTY_CONTENT'),
    ({'text':'provider-input-sentinel'},'FIELD_STRUCTURE'), ('broken-json','JSON_PARSE')])
def test_adapter_reports_only_safe_failure_category(raw,kind):
    req=request("utterance")
    async def run():
        content=json.dumps(raw,ensure_ascii=False) if isinstance(raw,dict) else raw
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':content}}]}))) as client:
            gateway=DeepSeekGateway(config(),client=client)
            with pytest.raises(InvalidModelResult) as error: await gateway.generate(req)
            assert error.value.failure_type==kind
            assert 'provider-input-sentinel' not in str(error.value)
    asyncio.run(run())


@pytest.mark.parametrize('finish,content,kind',[('length','{"sentences":','OUTPUT_TRUNCATED'),('stop','', 'EMPTY_CONTENT')])
def test_adapter_classifies_truncation_and_empty_without_response_dump(finish,content,kind):
    req=request("utterance")
    async def run():
        response={'choices':[{'finish_reason':finish,'message':{'content':content,'reasoning_content':'hidden-sentinel'}}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=response))) as client:
            with pytest.raises(InvalidModelResult) as error: await DeepSeekGateway(config(),client=client).generate(req)
            assert error.value.failure_type==kind
    asyncio.run(run())


class RecoveryGateway(ControlledGateway):
    def __init__(self, *, bad_opening=False, permanent=False, host_task='linking'):
        super().__init__();self.bad_opening=bad_opening;self.permanent=permanent
        self.summary_release.set()
        self.host_task=host_task

    async def generate(self,req):
        if req.task=='host_control':
            self.requests.append(req)
            return {'task':'host_control','action':'end' if len(req.messages)>=6 else self.host_task if len(req.messages)>=2 else 'continue','public_focus':'请澄清真实前提。'}
        if req.task=='utterance' and (req.host_task==self.host_task or self.bad_opening and req.host_task=='opening'):
            self.requests.append(req)
            if self.permanent or getattr(req,'validation_feedback',None) is None:
                return {'task':'utterance','sentences':['一。二。三。']}
            return {'task':'utterance','sentences':['请区分这些前提，并说明其依据。']}
        return await super().generate(req)


def test_correction_feedback_and_diagnostics_survive_restart(tmp_path):
    settings=Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=1)
    gateway=RecoveryGateway()
    with TestClient(create_app(settings)) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        snapshot=wait_for(client,did,'COMPLETED')
        host_calls=[r for r in gateway.requests if r.task=='utterance' and r.host_task=='linking']
        assert host_calls[0].validation_feedback is None
        assert host_calls[1].validation_feedback=='SENTENCE_BOUNDARY' and host_calls[1].attempt==2
        response=client.get(f'/api/discussions/{did}/diagnostics')
        assert response.status_code==200
        rows=response.json()['items'];failures=[r for r in rows if r['outcome']=='FAILED']
        assert failures and all(r['failure_type']=='SENTENCE_BOUNDARY' for r in failures)
        assert all(r['actor_kind']=='HOST' and r['message_position']>=3 and r['attempt']==1 for r in failures)
        assert not any(r['outcome']=='HOST_SKIPPED' for r in rows)
        expected=response.json()
    with TestClient(create_app(settings)) as client:
        assert client.get(f'/api/discussions/{did}/diagnostics').json()==expected
        assert client.get(f'/api/discussions/{did}').json()['messages']==snapshot['messages']


@pytest.mark.parametrize('host_task',['linking','followup'])
def test_permanent_nonopening_failure_skips_only_twice_and_then_stops(tmp_path,host_task):
    gateway=RecoveryGateway(permanent=True,host_task=host_task)
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=1))) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        snapshot=wait_for(client,did,'FAILED')
        assert len(snapshot['messages'])==4  # opening, expert, two expert responses after skips
        assert not any(m['kind']==host_task for m in snapshot['messages'])
        rows=client.get(f'/api/discussions/{did}/diagnostics').json()['items']
        assert sum(r['outcome']=='HOST_SKIPPED' for r in rows)==2
        assert [m['turn_no'] for m in snapshot['messages']]==[1,2,3,4]
        with client.app.state.database.connect() as conn:
            assert not conn.execute("SELECT 1 FROM turn_claims WHERE status IN ('PREPARING','SPEAKING')").fetchone()


def test_opening_is_never_skipped(tmp_path):
    gateway=RecoveryGateway(bad_opening=True,permanent=True)
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=1))) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        assert wait_for(client,did,'FAILED')['messages']==[]
        rows=client.get(f'/api/discussions/{did}/diagnostics').json()['items']
        assert not any(r['outcome']=='HOST_SKIPPED' for r in rows)


@pytest.mark.parametrize('bad_content,category', [('broken-json','JSON_PARSE'), ('{"sentences":["一。二。三。"]}','SENTENCE_BOUNDARY')])
def test_http_retry_receives_fixed_correction_context_without_previous_response(bad_content,category):
    from types import SimpleNamespace
    from backend.app.engine import DiscussionEngine
    seen=[]
    def upstream(req):
        context=json.loads(json.loads(req.content)['messages'][1]['content']);seen.append(context)
        body=answer({'sentences':['这次只回答一个关键问题。']})
        if len(seen)==1: body['choices'][0]['message']['content']=bad_content
        return httpx.Response(200,json=body)
    req=request("utterance")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            g=DeepSeekGateway(config(),client=client)
            engine=DiscussionEngine(SimpleNamespace(repository=None,_db_call=None,settings=config(),gateway_getter=lambda:g,semaphore=asyncio.Semaphore(1),closing=False))
            engine.deadline=time.monotonic()+5
            assert (await engine.call_model(req)).sentences==('这次只回答一个关键问题。',)
        assert seen[1]['output_correction']['failure_type']==category
        assert seen[1]['output_correction']['constraint']
        assert '一。二。三。' not in json.dumps(seen[1],ensure_ascii=False)
    asyncio.run(run())


def test_one_exhausted_host_call_can_resume_and_complete(tmp_path):
    class OnceGateway(RecoveryGateway):
        async def generate(self,req):
            if req.task=='utterance' and req.host_task=='linking' and len(req.messages)>2:
                self.requests.append(req)
                return {'task':'utterance','sentences':['刚才的条件已澄清，请继续核对证据。']}
            return await super().generate(req)
    gateway=OnceGateway(permanent=True)
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3'))) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        snap=wait_for(client,did,'COMPLETED')
        # A submitted linking gives experts a response chance before host control runs again.
        assert len(snap['messages'])==7 and snap['messages'][2]['kind'] not in ('linking','followup')
        assert sum(r['outcome']=='HOST_SKIPPED' for r in client.get(f'/api/discussions/{did}/diagnostics').json()['items'])==1
        assert [m['turn_no'] for m in snap['messages']]==list(range(1,8))


def test_nonretryable_service_failure_is_never_host_recovery(tmp_path):
    from backend.app.model_gateway import ModelServiceError
    class AuthGateway(RecoveryGateway):
        async def generate(self,req):
            if req.task=='utterance' and req.host_task=='linking':
                self.requests.append(req)
                raise ModelServiceError('MODEL_AUTH_FAILED',False)
            return await super().generate(req)
    gateway=AuthGateway()
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3'))) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        snap=wait_for(client,did,'FAILED')
        assert snap['discussion']['failure_code']=='MODEL_AUTH_FAILED' and len(snap['messages'])==2
        calls=[r for r in gateway.requests if r.task=='utterance' and r.host_task=='linking']
        assert len(calls)==1
        assert not any(r['outcome']=='HOST_SKIPPED' for r in client.get(f'/api/discussions/{did}/diagnostics').json()['items'])


@pytest.mark.parametrize('text',['一。二。三。','他说：“一。二。三。”','“问？”已经回答。另一个问题。第三个问题。'])
def test_quotes_do_not_hide_multiple_sentences(text):
    from pydantic import ValidationError
    with pytest.raises(ValidationError): UtteranceResult(task='utterance',sentences=[text])


def test_recovery_disabled_fails_without_synthetic_message(tmp_path):
    gateway=RecoveryGateway(permanent=True)
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=1,discussion_host_skip_limit=0))) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        assert len(wait_for(client,did,'FAILED')['messages'])==2
        assert not any(r['outcome']=='HOST_SKIPPED' for r in client.get(f'/api/discussions/{did}/diagnostics').json()['items'])


def test_failed_recovery_write_rolls_back_and_fails_safely(tmp_path):
    gateway=RecoveryGateway(permanent=True)
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=1))) as client:
        client.app.state.model_gateway=gateway
        with client.app.state.database.connect() as conn:
            conn.execute("CREATE TRIGGER block_skip BEFORE INSERT ON model_diagnostics WHEN NEW.outcome='HOST_SKIPPED' BEGIN SELECT RAISE(ABORT,'private-write-sentinel'); END")
        did,_=start_ready(client);snap=wait_for(client,did,'FAILED')
        assert snap['discussion']['failure_code']=='DATABASE_UNAVAILABLE' and len(snap['messages'])==2
        response=client.get(f'/api/discussions/{did}/diagnostics')
        assert 'private-write-sentinel' not in response.text
        assert not any(r['outcome']=='HOST_SKIPPED' for r in response.json()['items'])


def test_diagnostics_are_scoped_paginated_and_do_not_echo_untrusted_errors(tmp_path,caplog):
    gateway=RecoveryGateway()
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=1))) as client:
        client.app.state.model_gateway=gateway
        a,_=start_ready(client);b,_=start_ready(client)
        sa=wait_for(client,a,'COMPLETED');sb=wait_for(client,b,'COMPLETED')
        assert client.get(f'/api/discussions/{a}/diagnostics',params={'run_id':sb['discussion']['run_id']}).status_code==404
        first=client.get(f'/api/discussions/{a}/diagnostics',params={'limit':2}).json()
        second=client.get(f'/api/discussions/{a}/diagnostics',params={'limit':2,'before':first['next_before']}).json()
        assert all(r['discussion_id']==a for r in first['items']+second['items'])
        assert {r['id'] for r in first['items']}.isdisjoint(r['id'] for r in second['items'])
        assert client.get(f'/api/discussions/{a}/diagnostics',params={'limit':101}).status_code==422
        class UntrustedGateway(RecoveryGateway):
            async def generate(self,req):
                if req.task=='utterance': raise RuntimeError('private-response-sentinel')
                return await super().generate(req)
        client.app.state.model_gateway=UntrustedGateway();c,_=start_ready(client)
        wait_for(client,c,'FAILED');safe=client.get(f'/api/discussions/{c}/diagnostics').text
        assert 'private-response-sentinel' not in safe+caplog.text
        assert 'INTERNAL_ERROR' in safe


def test_cancellation_during_corrected_attempt_rejects_late_output(tmp_path):
    class CancelGateway(RecoveryGateway):
        def __init__(self):super().__init__();self.waiting=threading.Event()
        async def generate(self,req):
            if req.task=='utterance' and req.host_task=='linking' and getattr(req,'attempt',1)==2:
                self.requests.append(req);self.waiting.set()
                try: await asyncio.sleep(10)
                except asyncio.CancelledError: return {'task':'utterance','sentences':['这是取消后迟到的句子。']}
            return await super().generate(req)
    gateway=CancelGateway();settings=Settings(_env_file=None,database_path=tmp_path/'db.sqlite3',model_timeout_seconds=30)
    app=create_app(settings)
    with TestClient(app) as client:
        client.app.state.model_gateway=gateway;did,_=start_ready(client)
        assert gateway.waiting.wait(2)
        client.portal.call(client.app.state.tasks.close)
        snap=client.get(f'/api/discussions/{did}').json()
        assert snap['discussion']['state']=='INTERRUPTED' and len(snap['messages'])==2
        rows=client.get(f'/api/discussions/{did}/diagnostics').json()['items']
        assert any(r['outcome']=='CANCELLED' and r['attempt']==2 for r in rows)
        assert not any(r['outcome']=='HOST_SKIPPED' for r in rows)
        assert not app.state.tasks.run_tasks and not app.state.tasks.database_workers


def test_skipped_claim_cannot_be_replayed_or_commit_a_late_message(tmp_path):
    from uuid import uuid4
    from backend.app.contracts import StartDiscussion,IntentResult
    from backend.app.engine import ModelCallFailure
    from backend.tests.test_lifecycle_api import create
    from backend.tests.test_roster_tasks import generate
    settings=Settings(_env_file=None,database_path=tmp_path/'db.sqlite3')
    with TestClient(create_app(settings)) as client:
        did=create(client)['discussion']['id'];generate(client,did);wait_for(client,did,'READY')
        repo=client.app.state.repository;started=repo.start(did,StartDiscussion(roster_revision=1),uuid4(),settings)
        rid=started.body['run_id'];ctx=repo.begin_cycle(did,rid)
        host=next(p.id for p in ctx.snapshot.participants if p.kind=='HOST')
        claim=repo.prepare_turn(ctx,host,host_task='opening');assert repo.mark_speaking(ctx,claim.id)
        assert repo.commit_turn(ctx,claim.id,{'task':'utterance','sentences':['先讨论条件。']})
        ctx=repo.begin_cycle(did,rid);actor=next(p.id for p in ctx.snapshot.participants if p.kind=='EXPERT')
        assert repo.record_intents(ctx,{actor:IntentResult(task='intent',kind='REQUEST',relevance=80,public_focus='需要证据。')})
        claim=repo.prepare_turn(ctx,actor,participation_kind='REQUEST');repo.mark_speaking(ctx,claim.id)
        assert repo.commit_turn(ctx,claim.id,{'task':'utterance','sentences':['我建议核对证据。']})
        ctx=repo.begin_cycle(did,rid);claim=repo.prepare_turn(ctx,host,host_task='followup');repo.mark_speaking(ctx,claim.id)
        failure=ModelCallFailure('MODEL_RESULT_INVALID',failure_type='SENTENCE_COUNT',attempts=2)
        assert repo.skip_host_turn(ctx,claim.id,failure,2)=='SKIPPED'
        assert repo.skip_host_turn(ctx,claim.id,failure,2)=='STOPPED'
        assert not repo.commit_turn(ctx,claim.id,{'task':'utterance','sentences':['这条迟到结果不应出现。']})
        assert len(repo.snapshot(did).messages)==2
        assert sum(r.outcome=='HOST_SKIPPED' for r in repo.diagnostics(did).items)==1
