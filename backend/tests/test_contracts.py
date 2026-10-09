import asyncio
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.contracts import CreateDiscussion, ModelRequest, ModelResultAdapter, EventAdapter
from backend.app.model_gateway import DeterministicModelGateway, InvalidModelResult, validate_result


@pytest.mark.parametrize('topic,count', [('', 4), ('  ', 4), ('x' * 501, 4), ('议题', 1), ('议题', 7), ('议题', True), ('议题', '4')])
def test_create_rejects_bad_input(topic, count):
    with pytest.raises(ValidationError):
        CreateDiscussion(topic=topic, expert_count=count)


def test_create_defaults_and_forbids_extra():
    assert CreateDiscussion(topic='  测试  ').model_dump() == {'topic': '测试', 'expert_count': 4}
    with pytest.raises(ValidationError):
        CreateDiscussion(topic='测试', api_key='not-allowed')


def test_roster_is_deterministic_and_request_scoped():
    request = ModelRequest(task='roster', discussion_id=uuid4(), topic='是否推行四天工作制？')
    gateway = DeterministicModelGateway()
    first = asyncio.run(gateway.generate(request))
    assert first == asyncio.run(gateway.generate(request))
    assert len(first.participants) == 5
    assert all(p.discussion_id == request.discussion_id for p in first.participants)
    assert len({p.color for p in first.participants}) == 5
    raw = first.model_dump(mode='json')
    raw['participants'] = raw['participants'][:-1]
    with pytest.raises(InvalidModelResult):
        validate_result(request, raw)
    raw = first.model_dump(mode='json')
    raw['participants'][0]['discussion_id'] = str(uuid4())
    with pytest.raises(InvalidModelResult):
        validate_result(request, raw)


@pytest.mark.parametrize('raw', [
    {'task': 'utterance', 'sentences': []},
    {'task': 'utterance', 'sentences': ['一。', '二。', '三。']},
    {'task': 'utterance', 'sentences': ['一。二。']},
    {'task': 'utterance', 'sentences': ['   ']},
    {'task': 'summary', 'content': '总结', 'reasoning': 'hidden'},
])
def test_model_shape_rejects_invalid_or_hidden_content(raw):
    with pytest.raises(ValidationError):
        ModelResultAdapter.validate_python(raw)


def test_valid_short_utterance():
    result = ModelResultAdapter.validate_python({'task': 'utterance', 'sentences': ['成本下降 3.5%。', '但仍需验证！']})
    assert len(result.sentences) == 2


def test_all_mock_tasks_validate_and_do_not_share_context():
    gateway = DeterministicModelGateway()
    request = ModelRequest(task='roster', discussion_id=uuid4(), topic='测试')
    roster = asyncio.run(gateway.generate(request))
    for task in ('intent', 'utterance', 'host_control', 'insights', 'summary'):
        req = ModelRequest(task=task, discussion_id=request.discussion_id, topic='测试', run_id=uuid4(), participants=roster.participants, actor_id=roster.participants[1 if task == 'intent' else 0].id)
        output = asyncio.run(gateway.generate(req))
        assert output.task == task
    with pytest.raises(ValidationError):
        ModelRequest(task='utterance', discussion_id=uuid4(), topic='另一个讨论', run_id=uuid4(), participants=roster.participants, actor_id=roster.participants[0].id)


def test_event_envelope_and_payload_agree():
    discussion = str(uuid4())
    event = {'schema_version': 1, 'discussion_id': discussion, 'run_id': None, 'seq': 1, 'occurred_at': '2026-10-08T15:00:00Z', 'type': 'discussion.state_changed', 'payload': {'state': 'DRAFT', 'version': 1, 'failure_stage': None}}
    assert EventAdapter.validate_python(event).seq == 1
    with pytest.raises(ValidationError):
        EventAdapter.validate_python({**event, 'seq': 0})
    with pytest.raises(ValidationError):
        EventAdapter.validate_python({**event, 'type': 'unknown'})
    with pytest.raises(ValidationError):
        EventAdapter.validate_python({**event, 'occurred_at': '2026-10-08T15:00:00'})


def test_context_requires_complete_roster_and_appropriate_actor():
    gateway = DeterministicModelGateway()
    request = ModelRequest(task='roster', discussion_id=uuid4(), topic='测试')
    roster = asyncio.run(gateway.generate(request))
    base = dict(discussion_id=request.discussion_id, topic='测试', run_id=uuid4(), participants=roster.participants)
    with pytest.raises(ValidationError):
        ModelRequest(task='intent', actor_id=roster.participants[0].id, **base)
    with pytest.raises(ValidationError):
        ModelRequest(task='host_control', actor_id=roster.participants[1].id, **base)
    with pytest.raises(ValidationError):
        ModelRequest(task='summary', **{**base, 'participants': roster.participants[:-1]})


def test_roster_event_requires_complete_nonduplicated_roles():
    event = {'schema_version': 1, 'discussion_id': str(uuid4()), 'run_id': None, 'seq': 1, 'occurred_at': '2026-10-09T00:00:00Z', 'type': 'roster.ready', 'payload': {'roster_revision': 1, 'participants': []}}
    with pytest.raises(ValidationError):
        EventAdapter.validate_python(event)
