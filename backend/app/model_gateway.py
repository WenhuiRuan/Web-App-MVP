"""No network calls, no shared chat memory and no discussion scheduling."""
import asyncio
from typing import Protocol
from uuid import uuid5

from pydantic import BaseModel, ValidationError
from .text_rules import CLOSERS, sentence_count

from .contracts import ModelRequest, ModelResult, ModelResultAdapter, validate_insight_evidence


class InvalidModelResult(ValueError):
    def __init__(self, failure_type='RESULT_CONSTRAINT'):
        self.failure_type = failure_type if failure_type in VALIDATION_FAILURES else 'RESULT_CONSTRAINT'
        super().__init__('MODEL_RESULT_INVALID')


VALIDATION_FAILURES = frozenset({'EMPTY_CONTENT','OUTPUT_TRUNCATED','OUTPUT_REJECTED','JSON_PARSE',
    'FIELD_STRUCTURE','SENTENCE_COUNT','SENTENCE_BOUNDARY','SENTENCE_LENGTH','UTTERANCE_LENGTH','RESULT_CONSTRAINT'})


def check_utterance(sentences):
    if not isinstance(sentences,(tuple,list)) or any(not isinstance(s,str) for s in sentences):
        raise InvalidModelResult('FIELD_STRUCTURE')
    if not 1<=len(sentences)<=2: raise InvalidModelResult('SENTENCE_COUNT')
    for text in sentences:
        if not text.strip(): raise InvalidModelResult('EMPTY_CONTENT')
        if len(text.strip())>200: raise InvalidModelResult('SENTENCE_LENGTH')
        if sentence_count(text.strip())!=1: raise InvalidModelResult('SENTENCE_BOUNDARY')


MODEL_FAILURE_CODES = frozenset({'MODEL_TIMEOUT', 'MODEL_RESULT_INVALID', 'TASK_FAILED',
    'DATABASE_UNAVAILABLE', 'MODEL_REQUEST_INVALID', 'MODEL_AUTH_FAILED',
    'MODEL_BALANCE_EXHAUSTED', 'MODEL_NOT_FOUND', 'MODEL_RATE_LIMITED',
    'MODEL_SERVICE_UNAVAILABLE', 'MODEL_CONNECTION_FAILED'})


class ModelServiceError(Exception):
    """Safe provider-independent failure: never include response bodies or credentials."""
    def __init__(self, code, retryable=False, retry_after=0):
        self.code = code if code in MODEL_FAILURE_CODES else 'TASK_FAILED'
        self.retryable = retryable
        self.retry_after = min(5.0, max(0.0, float(retry_after)))
        super().__init__(self.code)


class ModelGateway(Protocol):
    # Multi-request adapters may opt into multi_step_synthesis=True. They must
    # enforce per-HTTP deadlines; the engine still owns the finite task budget.
    async def generate(self, request: ModelRequest) -> ModelResult: ...


def utterance_text(result):
    # A terminal inside a closing quote already ends the sentence; don't append twice.
    value=''.join(s if s.rstrip(CLOSERS)[-1:] in '。！？!?.' else s+'。' for s in result.sentences)
    if len(value)>400:
        raise InvalidModelResult('UTTERANCE_LENGTH')
    return value


def validate_result(request: ModelRequest, raw: object) -> ModelResult:
    """Never propagate raw provider output or validation input to callers."""
    try:
        if request.task=='utterance':
            value=raw.model_dump() if isinstance(raw,BaseModel) else raw
            if not isinstance(value,dict) or 'sentences' not in value: raise InvalidModelResult('FIELD_STRUCTURE')
            check_utterance(value['sentences'])
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
        if result.task=='host_control':
            if result.addressed_actor_id and not any(p.id==result.addressed_actor_id and p.kind=='EXPERT' for p in request.participants): raise ValueError('foreign addressed expert')
            if result.target_message_id and result.target_message_id not in message_ids: raise ValueError('foreign host target')
            if result.action in ('continue','end') and (result.addressed_actor_id or result.target_message_id): raise ValueError('no host question to bind')
        if result.task=='utterance':
            utterance_text(result)
        if result.task == 'insights':
            if len({i.id for i in result.items}) != len(result.items):
                raise ValueError('duplicate insight')
            if any(not set(i.source_message_ids) <= message_ids for i in result.items):
                raise ValueError('foreign source')
            validate_insight_evidence(request.participants, request.messages, result.items)
        return result
    except InvalidModelResult:
        raise
    except ValidationError:
        raise InvalidModelResult('FIELD_STRUCTURE') from None
    except (ValueError, TypeError):
        raise InvalidModelResult() from None


class DeterministicModelGateway:
    async def generate(self, request: ModelRequest) -> ModelResult:
        if request.task!='roster':
            await asyncio.sleep(.002)
        if request.task == 'roster':
            personas = [('主持人', '圆桌主持', '梳理问题与分歧'), ('林衡', '产品研究员', '关注用户价值'), ('陈谨', '风险分析师', '关注风险与边界'), ('周实', '工程师', '关注执行成本'), ('沈知', '社会研究者', '关注群体影响'), ('许远', '战略顾问', '关注长期收益'), ('顾微', '体验设计师', '关注参与者体验')]
            colors = ['#64748B', '#2563EB', '#D97706', '#059669', '#9333EA', '#DB2777', '#0891B2']
            raw = {'task': 'roster', 'participants': [
                {'id': uuid5(request.discussion_id, f'{request.roster_revision}:{index}'), 'discussion_id': request.discussion_id, 'roster_revision': request.roster_revision, 'kind': 'HOST' if index == 0 else 'EXPERT', 'name': name, 'title': title, 'stance': stance, 'color': colors[index]}
                for index, (name, title, stance) in enumerate(personas[:request.expert_count + 1])
            ]}
        elif request.task == 'intent':
            actor=next(p for p in request.participants if p.id==request.actor_id)
            seed=int(actor.id.hex[-4:],16)
            target=next((m for m in reversed(request.messages) if m.participant_id!=actor.id),None)
            kind='PASS' if (seed+len(request.messages))%5==0 else ('REBUT' if seed%2 else 'SUPPLEMENT') if target else 'REQUEST'
            raw = {'task': 'intent', 'kind':kind, 'target_message_id':target.id if target and kind in ('REBUT','SUPPLEMENT') else None,'relevance':50+(seed+len(request.messages)*11)%51,'public_focus':f'模拟：{actor.stance}'}
        elif request.task == 'utterance':
            actor=next(p for p in request.participants if p.id==request.actor_id)
            host_lines={'opening':'本场先梳理议题的价值、成本与边界。','followup':'请进一步说明适用条件和验证方式。','linking':'目前已有不同视角，请回应前文并区分证据与假设。'}
            if request.host_task:
                sentences=[host_lines[request.host_task]]
            else:
                target=next((m.turn_no for m in request.messages if m.id==request.target_message_id),None)
                sentences=[f'从{actor.stance}的角度，我对第{target}条发言提出{request.participation_kind}意见。' if target else f'从{actor.stance}的角度，需要先验证方案的适用条件。','这是确定性模型的工程演示内容。']
            raw = {'task':'utterance','sentences':sentences}
        elif request.task == 'host_control':
            raw = {'task':'host_control','action':'end' if len(request.messages)>=8 else 'linking' if len(request.messages)%3==0 else 'continue','public_focus':'模拟：梳理适用条件与已公开分歧。'}
        elif request.task == 'insights':
            experts={p.id for p in request.participants if p.kind=='EXPERT'}
            by_actor={}
            for message in request.messages:
                if message.participant_id in experts and '这是确定性模型的工程演示内容' in message.content:
                    by_actor[message.participant_id]=message
            sources=[m.id for m in list(by_actor.values())[:2]]
            raw = {'task': 'insights', 'items': [] if len(sources)<2 else [{'id':uuid5(request.run_id,f'insight:{request.through_turn}:demo'),'kind':'consensus','content':'两位专家均明确声明其发言是确定性模型的工程演示内容。','source_message_ids':sources}]}
        else:
            points=[m.content[:120] for m in request.messages if m.kind=='statement'][:3]
            consensus=[i.content for i in request.insights.items if i.kind=='consensus']
            differences=[i.content for i in request.insights.items if i.kind=='disagreement']
            raw = {'task': 'summary', 'content': f'主持人总结（确定性模拟）：围绕“{request.topic}”，已记录{request.through_turn}条正式发言。\n主要观点：'+('；'.join(points) if points else '尚无专家正式发言，证据不足。')+'\n已有共识：'+('；'.join(consensus) if consensus else '目前没有充分来源支持的共同认可观点。')+'\n未解决分歧：'+('；'.join(differences) if differences else '未提取到有充分依据的具体分歧，仍需进一步验证。')+'\n下一步：核对正式来源与适用条件。本结果仅验证工程流程，不代表真实模型分析。'}
        return validate_result(request, raw)
