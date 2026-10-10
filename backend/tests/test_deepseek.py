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


def checks(**overrides):
    return dict(authors_correct=True, same_object=True, compatible_scope=True,
                every_condition_supported=True, explicit_positions=True, proposal_preserved=True) | overrides


def summary_review(introduction='主持人总结：仅认可有限试点，细则尚未确认。', **overrides):
    return dict(introduction=introduction, positions=[], consensus_indices=[], disagreement_indices=[], pending=[]) | overrides


@pytest.mark.parametrize('task', ['roster','intent','utterance','host_control','insights','summary'])
def test_six_tasks_send_json_non_thinking_and_bind_identity(task):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request(task); seen=[]
    outputs={'roster':{'participants':[{'kind':'HOST' if i==0 else 'EXPERT','name':f'嘉宾{i}','title':f'专业{i}','stance':f'观点{i}'} for i in range(5)]},'intent':{'kind':'REBUT','target_turn':1,'relevance':85,'public_focus':'课堂纪律'},'utterance':{'sentences':['需要核对执行成本。']},'host_control':{'action':'followup','public_focus':'请比较边界'},'insights':{'items':[{'kind':'consensus','content':'两位专家认可有限试点。','source_turns':[2,3],'evidence':[{'turn':2,'quote':'我认可有限试点'},{'turn':3,'quote':'我认可有限试点'}]}]},'summary':{'content':'主持人总结：认可有限试点，执行成本仍需验证。'}}
    async def run():
        def upstream(http_request):
            seen.append(json.loads(http_request.content)); assert http_request.url.path=='/chat/completions'
            assert http_request.headers['Authorization']=='Bearer private-test-key'
            context=json.loads(seen[-1]['messages'][1]['content'])
            output={'reviews':[{'index':i,'checks':checks(),'content':point['content'],'source_turns':point['source_turns']} for i,point in enumerate(context['candidate']['items'])]} if task=='insights' and 'candidate' in context else summary_review() if task=='summary' and 'candidate' in context else outputs[task]
            return httpx.Response(200,json=answer(output))
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


def test_opt_in_metrics_sink_retains_each_call_and_drops_untrusted_model_text():
    from backend.app.deepseek_gateway import DeepSeekGateway
    saved=[]
    async def run():
        payload=answer({'action':'end','public_focus':'收束'},model='private-test-key reflected model')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            gateway=DeepSeekGateway(config(),client=client,metrics_sink=saved.append)
            await gateway.generate(req)
            assert len(saved)==1 and saved[0]['usage']['total_tokens']==120
            assert 'private-test-key' not in repr(saved) and 'NEVER-SAVE-THIS' not in repr(saved)
    req=request('host_control');asyncio.run(run())


@pytest.mark.parametrize('field,value',[('usage',[]),('choices',[]),('choices',[{'message':None,'finish_reason':'stop'}])])
def test_malformed_envelopes_are_invalid_not_internal_errors(field,value):
    from backend.app.deepseek_gateway import DeepSeekGateway
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=answer({},**{field:value})))) as client:
            with pytest.raises(InvalidModelResult): await DeepSeekGateway(config(),client=client).generate(request())
    asyncio.run(run())


@pytest.mark.parametrize('case',['missing','forged','host','duplicate','mismatch'])
def test_insights_require_exact_public_quotes_for_every_expert_source(case):
    from backend.app.deepseek_gateway import bind_result
    req=request('insights')
    point={'kind':'consensus','content':'两位专家认可有限试点。','source_turns':[2,3],
        'evidence':[{'turn':2,'quote':'我认可有限试点'},{'turn':3,'quote':'我认可有限试点'}]}
    if case=='missing': del point['evidence']
    if case=='forged': point['evidence'][1]['quote']='全体一致同意三天答复'
    if case=='host': point['source_turns']=[1,2,3];point['evidence'].append({'turn':1,'quote':'我认可有限试点'})
    if case=='duplicate': point['evidence'].append(point['evidence'][0])
    if case=='mismatch': point['evidence'].pop()
    with pytest.raises(InvalidModelResult): bind_result(req,json.dumps({'items':[point]},ensure_ascii=False))


def test_public_messages_carry_their_bound_author_without_shared_history():
    from backend.app.deepseek_gateway import public_context
    req=request('summary');context=public_context(req)
    for original,public in zip(req.messages,context['messages']):
        person=next(p for p in req.participants if p.id==original.participant_id)
        assert (public['speaker_name'],public['speaker_title'],public['speaker_kind'])==(person.name,person.title,person.kind)
        assert public['turn']==original.turn_no and public['content']==original.content


@pytest.mark.parametrize('url',['http://[','https://api.deepseek.com:bad','https://u:secret@api.deepseek.com','https://api.deepseek.com?key=secret'])
def test_invalid_base_urls_report_variable_name_without_constructing_http_client(url):
    from backend.app.deepseek_gateway import missing_configuration
    assert missing_configuration(config().model_copy(update={'model_base_url':url}))==['MODEL_BASE_URL']


@pytest.mark.parametrize('usage',['absent',None])
def test_missing_usage_is_unknown_and_does_not_discard_a_valid_answer(usage):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request('host_control');payload=answer({'action':'end','public_focus':'收束'})
    if usage=='absent':payload.pop('usage')
    else:payload['usage']=None
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            gateway=DeepSeekGateway(config(),client=client)
            assert (await gateway.generate(req)).action=='end'
            assert gateway.metrics[0]['usage'] is None
    asyncio.run(run())


@pytest.mark.parametrize('task', ['insights', 'summary', 'host_control'])
def test_evidence_tasks_do_not_receive_persona_stances_as_opinions(task):
    from backend.app.deepseek_gateway import public_context
    req = request(task)
    context = public_context(req)
    assert all('stance' not in p for p in context['participants'])
    assert all(p.stance not in json.dumps(context, ensure_ascii=False) for p in req.participants)
    # Actor generation still needs its persona, independently of evidence extraction.
    assert all('stance' in p for p in public_context(request('intent'))['participants'])


def test_summary_candidates_include_bound_source_authors_and_full_messages():
    from backend.app.deepseek_gateway import public_context
    from backend.app.contracts import InsightBatch
    req = request('summary')
    req = req.model_copy(update={'insights': InsightBatch(version=1, through_turn=3, items=[{
        'id': uuid4(), 'kind': 'consensus', 'content': '错误候选：所有人认可整个方案',
        'source_message_ids': [m.id for m in req.messages[1:]],
    }])})
    candidate = public_context(req)['insights'][0]
    assert candidate['semantic_status'] == 'candidate_requires_transcript_review'
    for source, original in zip(candidate['sources'], req.messages[1:]):
        person = next(p for p in req.participants if p.id == original.participant_id)
        assert source['speaker_name'] == person.name
        assert source['speaker_slot'] == req.participants.index(person)
        assert source['content'] == original.content and source['turn'] == original.turn_no


def test_extraction_evidence_context_excludes_host_questions_but_keeps_original_turns():
    from backend.app.deepseek_gateway import public_context
    req = request('insights')
    context = public_context(req)
    assert [m['turn'] for m in context['messages']] == [2, 3]
    assert all(m['speaker_kind'] == 'EXPERT' for m in context['messages'])
    assert context['through_turn'] == 3
    assert len(public_context(request('summary'))['messages']) == 3


@pytest.mark.parametrize('task', ['insights', 'summary'])
def test_only_grounding_review_result_can_leave_the_gateway(task):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req = request(task)
    draft = {'items': [{'kind': 'consensus', 'content': '全体同意全部细则', 'source_turns': [2, 3],
        'evidence': [{'turn': 2, 'quote': '我认可有限试点'}, {'turn': 3, 'quote': '我认可有限试点'}]}]} if task == 'insights' else {'content': '全体已经确认全部细则。'}
    revised = {'reviews': [{'index': 0, 'checks': checks(every_condition_supported=False), 'content': '细则缺少支持。', 'source_turns':[2,3]}]} if task == 'insights' else summary_review()
    seen = []
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            seen.append(context)
            return httpx.Response(200, json=answer(draft if len(seen) == 1 else revised))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway = DeepSeekGateway(config(), client=client)
            result = await gateway.generate(req)
            assert len(seen) == 2
            assert seen[1]['candidate'] == draft
            assert seen[1]['messages'] == seen[0]['messages']
            assert [m['stage'] for m in gateway.metrics] == ['draft', 'review']
            if task == 'insights': assert result.items == ()
            else: assert revised['introduction'] in result.content and '全体已经确认' not in result.content
    asyncio.run(run())


def test_cancel_grounding_review_never_returns_the_unreviewed_draft():
    from backend.app.deepseek_gateway import DeepSeekGateway
    req = request('summary')
    async def run():
        entered = asyncio.Event(); calls = []
        async def upstream(_):
            calls.append(1)
            if len(calls) == 1: return httpx.Response(200, json=answer({'content': '未复核草稿。'}))
            entered.set()
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway = DeepSeekGateway(config(), client=client)
            task = asyncio.create_task(gateway.generate(req))
            try:
                await asyncio.wait_for(entered.wait(), timeout=.5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                assert gateway.metrics[-1]['stage'] == 'review'
                assert gateway.metrics[-1]['status'] == 'cancelled'
            finally:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize('status,expected_calls,code', [(401, 2, 'MODEL_AUTH_FAILED'), (503, 4, 'MODEL_SERVICE_UNAVAILABLE')])
def test_review_http_failure_has_one_retry_owner_and_never_falls_back(status, expected_calls, code):
    import time
    from types import SimpleNamespace
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.app.engine import DiscussionEngine, ModelCallFailure
    req = request('summary')
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            return httpx.Response(status, headers={'Retry-After': '0'}) if 'candidate' in context else httpx.Response(200, json=answer({'content': '未复核总结。'}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway = DeepSeekGateway(config(), client=client)
            supervisor = SimpleNamespace(repository=None, _db_call=None, settings=config(), gateway_getter=lambda: gateway,
                semaphore=asyncio.Semaphore(1), closing=False)
            engine = DiscussionEngine(supervisor); engine.deadline = time.monotonic() + 10
            with pytest.raises(ModelCallFailure) as exc: await engine.call_model(req)
            assert exc.value.code == code and len(gateway.metrics) == expected_calls
    asyncio.run(run())


def test_review_cannot_extend_the_task_deadline_or_release_a_draft():
    import time
    from types import SimpleNamespace
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.app.engine import DiscussionEngine, RunDeadline
    req = request('summary')
    async def run():
        async def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            if 'candidate' in context: await asyncio.Event().wait()
            return httpx.Response(200, json=answer({'content': '未复核总结。'}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway = DeepSeekGateway(config(), client=client)
            supervisor = SimpleNamespace(repository=None, _db_call=None, settings=config(), gateway_getter=lambda: gateway,
                semaphore=asyncio.Semaphore(1), closing=False)
            engine = DiscussionEngine(supervisor); engine.deadline = time.monotonic() + .05
            with pytest.raises(RunDeadline): await engine.call_model(req)
            assert len(gateway.metrics) == 2 and gateway.metrics[-1]['status'] == 'cancelled'
    asyncio.run(run())


def test_review_cannot_invent_an_extra_candidate():
    from backend.app.deepseek_gateway import DeepSeekGateway
    req = request('insights')
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output = {'items': []} if 'candidate' not in context else {'reviews': [
                {'index': 0, 'checks': checks(), 'content': '凭空新增观点', 'source_turns':[2,3]}]}
            return httpx.Response(200, json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway = DeepSeekGateway(config(), client=client)
            with pytest.raises(InvalidModelResult): await gateway.generate(req)
            assert gateway.metrics[-1]['stage'] == 'review'
    asyncio.run(run())


def test_review_cannot_attribute_a_claim_to_a_known_non_source_participant():
    from backend.app.deepseek_gateway import DeepSeekGateway
    req = request('insights')
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output = {'items': [{'kind': 'consensus', 'content': '两位专家认可有限试点', 'source_turns': [2, 3],
                'evidence': [{'turn': 2, 'quote': '我认可有限试点'}, {'turn': 3, 'quote': '我认可有限试点'}]}]} if 'candidate' not in context else {
                'reviews': [{'index': 0, 'checks': checks(), 'content': req.participants[3].name + '也支持全部方案', 'source_turns':[2,3]}]}
            return httpx.Response(200, json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            with pytest.raises(InvalidModelResult): await DeepSeekGateway(config(), client=client).generate(req)
    asyncio.run(run())


def test_summary_binds_position_authors_and_copies_only_selected_existing_consensus():
    from backend.app.deepseek_gateway import DeepSeekGateway
    from backend.app.contracts import InsightBatch
    req = request('summary')
    req = req.model_copy(update={'insights': InsightBatch(version=1, through_turn=3, items=[{
        'id': uuid4(), 'kind': 'consensus', 'content': '两位专家共同建议有限试点，成本仍待验证。',
        'source_message_ids': [m.id for m in req.messages[1:]],
    }])})
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output = {'content':'错误草稿：全体已同意全部规则。'} if 'candidate' not in context else summary_review(
                introduction='本场比较试点边界。', positions=[{'speaker_slot':1,'source_turns':[2],'content':req.messages[1].content}], consensus_indices=[0])
            return httpx.Response(200, json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result = await DeepSeekGateway(config(), client=client).generate(req)
            assert req.participants[1].name in result.content
            assert req.insights.items[0].content in result.content
            assert '全体已同意' not in result.content
            assert '已有共识：' in result.content and '未解决分歧：尚无充分证据' in result.content
    asyncio.run(run())


@pytest.mark.parametrize('case',['author','consensus','disagreement'])
def test_summary_review_rejects_wrong_authors_or_new_insight_indices(case):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req = request('summary')
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            bad = summary_review()
            if case == 'author': bad['positions']=[{'speaker_slot':2,'source_turns':[2],'content':'个人建议。'}]
            else: bad[case+'_indices']=[0]
            return httpx.Response(200, json=answer(bad if 'candidate' in context else {'content':'草稿。'}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            with pytest.raises(InvalidModelResult): await DeepSeekGateway(config(), client=client).generate(req)
    asyncio.run(run())


@pytest.mark.parametrize('source_turns,valid', [([2,3], True), ([1,2,3], False)])
def test_point_review_can_keep_sources_but_cannot_expand_them(source_turns, valid):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req = request('insights')
    async def run():
        def upstream(http_request):
            context = json.loads(json.loads(http_request.content)['messages'][1]['content'])
            draft = {'items':[{'kind':'consensus','content':'有限试点','source_turns':[2,3],
                'evidence':[{'turn':2,'quote':'我认可有限试点'},{'turn':3,'quote':'我认可有限试点'}]}]}
            review = {'reviews':[{'index':0,'checks':checks(),'content':'两位专家共同建议有限试点。','source_turns':source_turns}]}
            return httpx.Response(200, json=answer(review if 'candidate' in context else draft))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            if valid: assert len((await gateway.generate(req)).items)==1
            else:
                with pytest.raises(InvalidModelResult): await gateway.generate(req)
    asyncio.run(run())


@pytest.mark.parametrize('both_support', [False, True])
def test_consensus_quantified_condition_must_be_explicit_in_each_retained_quote(both_support):
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request('insights')
    lines=['建议仅作为试验，连续两周超过基线才暂停。', '我同意选择该指标，但未判断暂停条件。']
    if both_support: lines[1]='我也建议连续两周超过基线才暂停，仅作为试验。'
    req=req.model_copy(update={'messages':tuple(m.model_copy(update={'content':lines[i-1]}) if i>0 else m for i,m in enumerate(req.messages))})
    point={'kind':'consensus','content':'两位专家共同建议连续两周超过基线才暂停，仅为提案。','source_turns':[2,3],
        'evidence':[{'turn':2,'quote':lines[0]},{'turn':3,'quote':lines[1]}]}
    async def run():
        def upstream(http_request):
            context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output={'reviews':[{'index':0,'source_turns':[2,3],'checks':checks(),'content':point['content']}]} if 'candidate' in context else {'items':[point]}
            return httpx.Response(200,json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            gateway=DeepSeekGateway(config(),client=client)
            if both_support: assert len((await gateway.generate(req)).items)==1
            else:
                with pytest.raises(InvalidModelResult) as exc: await gateway.generate(req)
                assert exc.value.validation_issue == 'consensus_quantity_unsupported'
    asyncio.run(run())


def test_utterance_receives_bound_target_content_and_unverified_focus_label():
    from backend.app.deepseek_gateway import public_context
    req=request('intent')
    req=req.model_copy(update={'task':'utterance','participation_kind':'SUPPLEMENT', 'target_message_id':req.messages[0].id})
    context=public_context(req)
    assert context['focus_is_unverified'] is True
    assert context['target_message']['turn']==req.messages[0].turn_no
    assert context['target_message']['speaker_name']==req.participants[0].name
    assert context['target_message']['content']==req.messages[0].content


def test_summary_position_cannot_change_source_alternatives_into_joint_requirements():
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request('summary')
    req=req.model_copy(update={'messages':tuple(m.model_copy(update={'content':'我建议保留视频协助或提供纸本说明。'}) if i==1 else m for i,m in enumerate(req.messages))})
    async def run():
        def upstream(http_request):
            context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output=summary_review(positions=[{'speaker_slot':1,'source_turns':[2],'content':'我建议保留视频协助和提供纸本说明。'}]) if 'candidate' in context else {'content':'待复核草稿。'}
            return httpx.Response(200,json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            with pytest.raises(InvalidModelResult) as exc: await DeepSeekGateway(config(),client=client).generate(req)
            assert exc.value.validation_issue=='summary_position_quote'
    asyncio.run(run())


def test_summary_pending_cannot_freely_merge_different_objects_into_a_conflict():
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request('summary')
    async def run():
        def upstream(http_request):
            context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output=summary_review(pending='三个不同指标的分母存在三方分歧。') if 'candidate' in context else {'content':'草稿。'}
            return httpx.Response(200,json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            with pytest.raises(InvalidModelResult): await DeepSeekGateway(config(),client=client).generate(req)
    asyncio.run(run())


def test_summary_pending_binds_a_public_source_and_a_limited_issue_label():
    from backend.app.deepseek_gateway import DeepSeekGateway
    req=request('summary')
    async def run():
        def upstream(http_request):
            context=json.loads(json.loads(http_request.content)['messages'][1]['content'])
            output=summary_review(pending=[{'turn':2,'quote':req.messages[1].content,'issue':'UNVERIFIED_PROPOSAL'}]) if 'candidate' in context else {'content':'草稿。'}
            return httpx.Response(200,json=answer(output))
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            result=await DeepSeekGateway(config(),client=client).generate(req)
            assert req.participants[1].name in result.content and req.messages[1].content in result.content
            assert '提案待验证' in result.content
    asyncio.run(run())
