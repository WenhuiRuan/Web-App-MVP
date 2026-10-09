"""No network calls, no shared chat memory and no discussion scheduling."""
from typing import Protocol
from uuid import uuid5

from pydantic import ValidationError

from .contracts import ModelRequest, ModelResult, ModelResultAdapter


class InvalidModelResult(ValueError):
    def __init__(self):
        super().__init__('MODEL_RESULT_INVALID')


class ModelGateway(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResult: ...


def utterance_text(result):
    value=''.join(s if s[-1] in '。！？!?.' else s+'。' for s in result.sentences)
    if len(value)>400:
        raise InvalidModelResult()
    return value


def validate_result(request: ModelRequest, raw: object) -> ModelResult:
    """Never propagate raw provider output or validation input to callers."""
    try:
        result = ModelResultAdapter.validate_python(raw)
        if result.task != request.task:
            raise ValueError('task mismatch')
        if result.task == 'roster':
            people = result.participants
            if len(people) != request.expert_count + 1 or sum(p.kind == 'HOST' for p in people) != 1:
                raise ValueError('roster count')
            for attribute in ('id', 'name', 'color'):
                if len({getattr(p, attribute) for p in people}) != len(people):
                    raise ValueError('duplicate roster field')
            if any(p.discussion_id != request.discussion_id or p.roster_revision != request.roster_revision for p in people):
                raise ValueError('roster scope')
        message_ids = {m.id for m in request.messages}
        if result.task == 'intent':
            if result.target_message_id and result.target_message_id not in message_ids:
                raise ValueError('foreign target')
            if result.kind in ('SUPPLEMENT', 'REBUT') and result.target_message_id is None:
                raise ValueError('missing target')
            if result.kind=='PASS' and result.target_message_id:
                raise ValueError('pass cannot respond')
            if result.target_message_id and any(m.id==result.target_message_id and m.participant_id==request.actor_id for m in request.messages):
                raise ValueError('self response')
        if result.task=='utterance':
            utterance_text(result)
        if result.task == 'insights':
            if len({i.id for i in result.items}) != len(result.items):
                raise ValueError('duplicate insight')
            if any(not set(i.source_message_ids) <= message_ids for i in result.items):
                raise ValueError('foreign source')
        return result
    except (ValidationError, ValueError, TypeError):
        raise InvalidModelResult() from None


class DeterministicModelGateway:
    async def generate(self, request: ModelRequest) -> ModelResult:
        if request.task == 'roster':
            personas = [('主持人', '圆桌主持', '梳理问题与分歧'), ('林衡', '产品研究员', '关注用户价值'), ('陈谨', '风险分析师', '关注风险与边界'), ('周实', '工程师', '关注执行成本'), ('沈知', '社会研究者', '关注群体影响'), ('许远', '战略顾问', '关注长期收益'), ('顾微', '体验设计师', '关注参与者体验')]
            colors = ['#64748B', '#2563EB', '#D97706', '#059669', '#9333EA', '#DB2777', '#0891B2']
            raw = {'task': 'roster', 'participants': [
                {'id': uuid5(request.discussion_id, f'{request.roster_revision}:{index}'), 'discussion_id': request.discussion_id, 'roster_revision': request.roster_revision, 'kind': 'HOST' if index == 0 else 'EXPERT', 'name': name, 'title': title, 'stance': stance, 'color': colors[index]}
                for index, (name, title, stance) in enumerate(personas[:request.expert_count + 1])
            ]}
        elif request.task == 'intent':
            raw = {'task': 'intent', 'kind': 'REBUT' if request.messages else 'REQUEST', 'target_message_id': request.messages[-1].id if request.messages else None, 'relevance': 70, 'public_focus': '模拟：准备从实施成本角度回应。'}
        elif request.task == 'utterance':
            raw = {'task': 'utterance', 'sentences': ['这是确定性模拟发言。', '正式讨论将在后续阶段实现。']}
        elif request.task == 'host_control':
            raw = {'task': 'host_control', 'action': 'followup', 'public_focus': '模拟：邀请补充边界条件。'}
        elif request.task == 'insights':
            raw = {'task': 'insights', 'items': []}
        else:
            raw = {'task': 'summary', 'content': f'确定性模拟摘要：目前上下文包含 {len(request.messages)} 条正式消息。此结果仅用于工程校验。'}
        return validate_result(request, raw)
