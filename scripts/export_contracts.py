"""Export target contracts separately from the currently mounted foundation API."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid5

from backend.app.config import Settings
from backend.app.contracts import ContractExamples, EventAdapter, ModelRequest
from backend.app.main import create_app
from backend.app.model_gateway import DeterministicModelGateway

ROOT = Path(__file__).resolve().parents[1]


def example_data():
    d = UUID('11111111-1111-4111-8111-111111111111')
    run = UUID('22222222-2222-4222-8222-222222222222')
    op = UUID('33333333-3333-4333-8333-333333333333')
    timestamp = '2026-10-09T00:00:00Z'
    gateway = DeterministicModelGateway()
    req = ModelRequest(task='roster', discussion_id=d, topic='是否推行四天工作制？')
    roster = asyncio.run(gateway.generate(req)).model_dump(mode='json')
    participants = roster['participants']
    message = {'id': str(uuid5(d, 'message-1')), 'discussion_id': str(d), 'run_id': str(run), 'participant_id': participants[0]['id'], 'turn_no': 1, 'kind': 'opening', 'content': '我们先讨论效率与成本。', 'created_at': timestamp}
    expert_messages=[{**message,'id':str(uuid5(d,f'message-{n}')),'participant_id':participants[n-1]['id'],'turn_no':n,'kind':'statement','content':text} for n,text in [(2,'我认可先小规模试点，成本上限需另行验证。'),(3,'我同意先试点，但成本上限仍有分歧。')]]
    messages=[message,*expert_messages]
    batch = {'version': 1, 'through_turn': 3, 'items': [
        {'id': str(uuid5(d, 'insight-1')), 'kind': 'consensus', 'content': '两位专家认可先进行小规模试点。', 'source_message_ids': [m['id'] for m in expert_messages]},
        {'id': str(uuid5(d, 'insight-2')), 'kind': 'disagreement', 'content': '成本上限仍需讨论。', 'source_message_ids': [m['id'] for m in expert_messages]}]}
    summary = {'content': '主要观点是先通过小规模试点验证方案。两位专家认可先试点，成本上限仍需进一步讨论。', 'through_turn': 3, 'created_at': timestamp}
    discussion = {'id': str(d), 'topic': req.topic, 'expert_count': 4, 'state': 'COMPLETED', 'version': 5, 'roster_revision': 1, 'run_id': str(run), 'failure_stage': None, 'created_at': timestamp, 'updated_at': timestamp}
    role_states = [{'participant_id': p['id'], 'state': 'IDLE', 'public_focus': '', 'version': 1} for p in participants]
    def event(seq, kind, payload, rid=run):
        return {'schema_version': 1, 'discussion_id': str(d), 'run_id': str(rid) if rid else None, 'seq': seq, 'type': kind, 'occurred_at': timestamp, 'payload': payload}
    events = [
        event(1, 'discussion.state_changed', {'state': 'DRAFT', 'version': 0}, None),
        event(2, 'roster.ready', {'roster_revision': 1, 'participants': participants}, None),
        event(3, 'discussion.state_changed', {'state': 'RUNNING', 'version': 3}),
        event(4, 'participant.status_changed', {**role_states[0], 'state': 'SPEAKING'}),
        event(5, 'turn.committed', message),
        event(6, 'turn.committed', expert_messages[0]),
        event(7, 'turn.committed', expert_messages[1]),
        event(8, 'insights.updated', batch),
        event(9, 'discussion.state_changed', {'state':'SUMMARIZING','version':4}),
        event(10, 'summary.ready', summary),
        event(11, 'discussion.state_changed', {'state': 'COMPLETED', 'version': 5}),
    ]
    # A standalone failure example, not a transition after COMPLETED.
    failure = event(1, 'operation.failed', {'operation_id': str(op), 'stage': 'roster', 'code': 'MODEL_TIMEOUT', 'message': '嘉宾生成超时，可重试。', 'retryable': True}, None)
    failure['discussion_id'] = '44444444-4444-4444-8444-444444444444'
    results = [roster]
    requests = [req]
    for task in ('intent', 'utterance', 'host_control', 'insights', 'summary'):
        context = ModelRequest(task=task, discussion_id=d, run_id=run, topic=req.topic, actor_id=participants[1 if task == 'intent' else 0]['id'], participants=participants, messages=messages,cycle=1,host_task='linking' if task=='utterance' else None,through_turn=3 if task in ('insights','summary') else None,insight_version=1 if task=='insights' else None,insights=batch if task=='summary' else {})
        results.append(asyncio.run(gateway.generate(context)).model_dump(mode='json'))
        requests.append(context)
    expert_context=ModelRequest(task='utterance',discussion_id=d,run_id=run,topic=req.topic,expert_count=4,actor_id=participants[1]['id'],participants=participants,messages=[message],cycle=2,participation_kind='REBUT',target_message_id=message['id'],public_focus='核对实施成本')
    requests.append(expert_context)
    return ContractExamples.model_validate({
        'create': {'topic': req.topic, 'expert_count': 4}, 'start': {'roster_revision': 1},
        'accepted': {'operation_id': str(op), 'discussion_id': str(d), 'state': 'RUNNING', 'run_id': str(run)},
        'snapshot': {'discussion': discussion, 'participants': participants, 'role_states': role_states, 'messages': messages, 'insights': batch, 'summary': summary, 'last_event_seq': 11},
        'listing': {'items': [discussion], 'next_cursor': None},
        'operation': {'id': str(op), 'discussion_id': str(d), 'kind': 'start', 'status': 'SUCCEEDED', 'error_code': None},
        'error': {'error': {'code': 'ROSTER_VERSION_CONFLICT', 'message': '阵容版本已变更，请刷新后确认。', 'retryable': False, 'request_id': str(op), 'details': []}},
        'events': [*events, failure, event(1, 'insights.status_changed', {'state':'FAILED','version':2,'through_turn':3,'error_code':'MODEL_TIMEOUT'})], 'model_request': req, 'model_requests':requests, 'model_results': results,
    }).model_dump(mode='json')


def contract_openapi():
    spec = create_app(Settings(_env_file=None)).openapi()
    spec['info']['title'] = 'AI Panel Studio — target HTTP and SSE contract'
    spec['info']['description'] = 'x-implemented marks mounted routes; false routes remain future design contracts.'
    schema = ContractExamples.model_json_schema()
    definitions = schema.pop('$defs')
    definitions['Event'] = {k: v for k, v in EventAdapter.json_schema().items() if k != '$defs'}
    translated = json.loads(json.dumps(definitions).replace('#/$defs/', '#/components/schemas/'))
    spec['components']['schemas'].update(translated)
    for methods in spec['paths'].values():
        for operation in methods.values():
            operation['x-implemented'] = True
    endpoints = [
        ('/api/discussions', 'post', 'CreateDiscussion', 'Snapshot', 201),
        ('/api/discussions', 'get', None, 'DiscussionList', 200),
        ('/api/discussions/{discussion_id}', 'get', None, 'Snapshot', 200),
        ('/api/discussions/{discussion_id}/roster-generation', 'post', None, 'OperationAccepted', 202),
        ('/api/discussions/{discussion_id}/start', 'post', 'StartDiscussion', 'OperationAccepted', 202),
        ('/api/discussions/{discussion_id}/summary-retry', 'post', None, 'OperationAccepted', 202),
        ('/api/discussions/{discussion_id}/operations/{operation_id}', 'get', None, 'Operation', 200),
        ('/api/discussions/{discussion_id}/events', 'get', None, None, 200),
    ]
    def response(name, description):
        return {'description': description, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/' + name}}}}
    for path, method, body, result, status in endpoints:
        if method in spec['paths'].get(path, {}):
            continue
        params = []
        for field in ('discussion_id', 'operation_id'):
            if '{' + field + '}' in path:
                params.append({'name': field, 'in': 'path', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}})
        if method == 'post':
            params.append({'name': 'Idempotency-Key', 'in': 'header', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}})
        operation = {'x-implemented': False, 'summary': 'Planned: ' + method.upper() + ' ' + path, 'parameters': params,
                     'responses': {str(code): response('ErrorResponse', label) for code, label in [(404, 'Not found'), (409, 'State / idempotency / cursor conflict'), (422, 'Validation failure'), (503, 'Unavailable'), (500, 'Internal failure')]}}
        if body:
            operation['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/' + body}}}}
        elif method == 'post':
            operation['requestBody'] = {'required': False, 'content': {'application/json': {'schema': {'type': 'object', 'additionalProperties': False, 'maxProperties': 0}}}}
        if result:
            operation['responses'][str(status)] = response(result, 'Success (idempotent replay uses original status and body)')
        else:
            operation['parameters'] += [
                {'name': 'after', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 0, 'default': 0}},
                {'name': 'Last-Event-ID', 'in': 'header', 'schema': {'type': 'string', 'pattern': r'^[0-9a-f-]{36}:[0-9]+$'}},
            ]
            operation['responses']['200'] = {'description': 'UTF-8 SSE stream; data conforms to Event', 'content': {'text/event-stream': {'schema': {'type': 'string'}}}, 'x-event-schema': {'$ref': '#/components/schemas/Event'}}
        if path == '/api/discussions' and method == 'get':
            operation['parameters'] += [
                {'name': 'status', 'in': 'query', 'schema': {'type': 'string', 'enum': ['active', 'all'], 'default': 'active'}},
                {'name': 'limit', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 20}},
                {'name': 'cursor', 'in': 'query', 'schema': {'type': 'string'}},
            ]
        spec['paths'].setdefault(path, {})[method] = operation
    stream = spec['paths']['/api/discussions/{discussion_id}/events']['get']
    stream['responses']['200']['x-event-schema'] = {'$ref': '#/components/schemas/Event'}
    return spec


def artifacts():
    return {
        ROOT / 'docs/contracts/schema.json': ContractExamples.model_json_schema(),
        ROOT / 'docs/contracts/openapi.json': contract_openapi(),
        ROOT / 'data/samples/contracts.json': example_data(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for path, value in artifacts().items():
        content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                raise SystemExit(f'Contract artifact is stale: {path.name}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8', newline='\n')
    print('Contract artifacts verified.' if args.check else 'Contract artifacts exported.')


if __name__ == '__main__':
    main()
