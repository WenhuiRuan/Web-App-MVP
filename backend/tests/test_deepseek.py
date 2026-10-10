import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import ModelRequest
from backend.app.main import create_app
from backend.app.model_gateway import DeterministicModelGateway, InvalidModelResult


def config(**overrides):
    return Settings(_env_file=None, model_provider='deepseek', model_base_url='https://api.deepseek.com', model_name='deepseek-flash', model_api_key='private-test-key', **overrides)


def request(task='roster'):
    did=uuid4(); roster=ModelRequest(task='roster',discussion_id=did,topic='大学是否应禁止课堂使用手机')
    if task=='roster': return roster
    people=asyncio.run(DeterministicModelGateway().generate(roster)).participants
    run=uuid4()
    messages=[{'id':uuid4(),'discussion_id':did,'run_id':rid,'participant_id':people[i].id,'turn_no':i+1,'kind':'opening' if i==0 else 'statement','content':'我认可有限试点，但执行成本需要单独验证。','created_at':'2026-10-10T00:00:00Z'} for i,rid in enumerate([run]*3)]
    return ModelRequest(task=task,discussion_id=did,run_id=run,topic=roster.topic,participants=people,messages=messages,actor_id=people[1 if task=='intent' else 0].id,cycle=1,
                        host_task='linking' if task=='utterance' else None,through_turn=3 if task in ('insights','summary') else None,insight_version=1 if task=='insights' else None)


def answer(raw, **extra):
    return {'model':'deepseek-flash','choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(raw,ensure_ascii=False),'reasoning_content':'NEVER-SAVE-THIS'}}], 'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_cache_hit_tokens':40},**extra}


@pytest.mark.parametrize('task', ['roster','intent','utterance','host_control','insights','summary'])
def test_six_tasks_send_json_non_thinking_and_bind_identity(task):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request(task); seen=[]
    outputs={'roster':{'participants':[{'kind':'HOST' if i==0 else 'EXPERT','name':f'嘉宾{i}','title':f'专业{i}','stance':f'观点{i}'} for i in range(5)]},'intent':{'kind':'REBUT','target_turn':1,'relevance':85,'public_focus':'课堂纪律'},'utterance':{'sentences':['需要核对执行成本。']},'host_control':{'action':'followup','public_focus':'请比较边界'},'insights':{'items':[{'kind':'consensus','content':'两位专家认可有限试点。','source_turns':[2,3]}]},'summary':{'content':'主持人总结：认可有限试点，执行成本仍需验证。'}}
    async def run():
        def upstream(http_request):
            seen.append(json.loads(http_request.content)); assert http_request.url.path=='/chat/completions'
            assert http_request.headers['Authorization']=='Bearer private-test-key'
            return httpx.Response(200,json=answer(outputs[task]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            result=await gateway.generate(req)
            assert result.task==task
            assert 'NEVER-SAVE-THIS' not in repr(gateway.metrics)
            assert gateway.metrics[-1]['usage']['total_tokens']==120
            assert seen[0]['thinking']=={'type':'disabled'} and seen[0]['response_format']=={'type':'json_object'}
            assert seen[0]['stream'] is False and 'json' in seen[0]['messages'][0]['content'].lower()
            assert req.topic in seen[0]['messages'][1]['content']
            if task=='roster': assert all(p.discussion_id==req.discussion_id and p.roster_revision==1 for p in result.participants)
            if task=='intent': assert result.target_message_id==req.messages[0].id
            if task=='insights': assert result.items[0].source_message_ids==tuple(m.id for m in req.messages[1:])
    asyncio.run(run())


@pytest.mark.parametrize('status,code,retryable',[(400,'MODEL_REQUEST_INVALID',False),(401,'MODEL_AUTH_FAILED',False),(403,'MODEL_AUTH_FAILED',False),(402,'MODEL_BALANCE_EXHAUSTED',False),(404,'MODEL_NOT_FOUND',False),(429,'MODEL_RATE_LIMITED',True),(500,'MODEL_SERVICE_UNAVAILABLE',True),(503,'MODEL_SERVICE_UNAVAILABLE',True)])
def test_http_errors_do_not_leak_upstream_body_or_key(status,code,retryable):
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.app.model_gateway import ModelServiceError
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,text='private-test-key provider secret',headers={'Retry-After':'1000'}))) as client:
            gateway=DeepSeekGateway(config(),client=client)
            with pytest.raises(ModelServiceError) as error: await gateway.generate(request())
            assert error.value.code==code and error.value.retryable==retryable
            assert 'private' not in str(error.value) and error.value.retry_after<=5
            assert len(gateway.metrics)==1
    asyncio.run(run())


@pytest.mark.parametrize('case',['empty','bad_json','length','foreign_target','foreign_source','provider_id','hidden_field'])
def test_invalid_provider_results_fail_without_persisting_private_output(case):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request('intent' if case=='foreign_target' else 'insights' if case=='foreign_source' else 'roster')
    raw={'participants':[{'kind':'HOST' if i==0 else 'EXPERT','name':f'人{i}','title':'专业','stance':'立场'} for i in range(5)]}
    if case=='provider_id': raw['participants'][0]['id']=str(uuid4())
    if case=='hidden_field': raw['reasoning']='NEVER-SAVE-THIS'
    if case=='foreign_target': raw={'kind':'REBUT','target_turn':99,'relevance':80,'public_focus':'回应'}
    if case=='foreign_source': raw={'items':[{'kind':'consensus','content':'观点','source_turns':[2,99]}]}
    payload=answer(raw)
    if case in ('empty','bad_json'): payload['choices'][0]['message']['content']='' if case=='empty' else '{'
    if case=='length': payload['choices'][0]['finish_reason']='length'
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            gateway=DeepSeekGateway(config(),client=client)
            with pytest.raises(InvalidModelResult): await gateway.generate(req)
            assert 'NEVER-SAVE-THIS' not in repr(gateway.metrics)
    asyncio.run(run())


def test_config_interpolation_process_priority_and_missing_variable_names(tmp_path,monkeypatch):
    from backend.app.deepseek_gateway import missing_configuration
    for key in ('MODEL_API_KEY','MODEL_PROVIDER','MODEL_BASE_URL','MODEL_NAME'): monkeypatch.delenv(key,raising=False)
    env=tmp_path/'.env';env.write_text('MODEL_PROVIDER=deepseek\nMODEL_BASE_URL=https://api.deepseek.com\nMODEL_NAME=file-model\nMODEL_API_KEY=${PANEL_API_KEY}\n')
    monkeypatch.setenv('PANEL_API_KEY','test-secret');monkeypatch.setenv('MODEL_NAME','process-model')
    settings=Settings(_env_file=env)
    assert settings.model_name=='process-model' and settings.model_api_key.get_secret_value()=='test-secret'
    assert missing_configuration(settings)==[]
    monkeypatch.delenv('MODEL_NAME')
    with TestClient(create_app(Settings(_env_file=None,model_provider='deepseek',database_path=tmp_path/'db'))) as client:
        response=client.get('/api/health/ready')
        assert response.status_code==503
        assert all(name in response.text for name in ('MODEL_BASE_URL','MODEL_NAME','MODEL_API_KEY'))


@pytest.mark.parametrize('status,expected_calls,code',[(401,1,'MODEL_AUTH_FAILED'),(429,2,'MODEL_RATE_LIMITED'),(503,2,'MODEL_SERVICE_UNAVAILABLE')])
def test_engine_is_only_retry_owner_and_preserves_error(status,expected_calls,code):
    import time
    from types import SimpleNamespace
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.app.engine import DiscussionEngine, ModelCallFailure
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,headers={'Retry-After':'0'}))) as client:
            gateway=DeepSeekGateway(config(),client=client)
            supervisor=SimpleNamespace(repository=None,_db_call=None,settings=config(),gateway_getter=lambda:gateway,semaphore=asyncio.Semaphore(1),closing=False)
            engine=DiscussionEngine(supervisor);engine.deadline=time.monotonic()+10
            with pytest.raises(ModelCallFailure) as error: await engine.call_model(request())
            assert error.value.code==code and len(gateway.metrics)==expected_calls
    asyncio.run(run())


def test_cancellation_closes_inflight_request_without_retry():
    from backend.app.deepseek_gateway import DeepSeekGateway
    async def run():
        entered=asyncio.Event();cancelled=asyncio.Event()
        async def upstream(_):
            entered.set()
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            task=asyncio.create_task(gateway.generate(request()))
            await entered.wait();task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert cancelled.is_set() and len(gateway.metrics)==1 and gateway.metrics[0]['status']=='cancelled'
    asyncio.run(run())


def test_gateway_timeout_is_safe_and_context_is_not_shared():
    from backend.app.deepseek_gateway import DeepSeekGateway,public_context
    from backend.app.model_gateway import ModelServiceError
    first=request('intent');second=request('intent')
    assert first.discussion_id != second.discussion_id
    assert str(first.discussion_id) not in json.dumps(public_context(second))
    async def run():
        def timeout(_): raise httpx.ReadTimeout('private-test-key')
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            with pytest.raises(ModelServiceError) as error: await gateway.generate(first)
            assert error.value.code=='MODEL_TIMEOUT' and error.value.retryable
            assert 'private' not in str(error.value)
    asyncio.run(run())
