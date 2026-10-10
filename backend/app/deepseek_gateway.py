"""Stateless Chat Completions adapter. Retry/cancellation budgets belong to the engine."""
import asyncio
import json
import time
import logging
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid5

import httpx
from pydantic import Field, StrictInt, ValidationError

from .contracts import Contract, ModelRequest
from .model_gateway import InvalidModelResult, ModelServiceError, validate_result

COLORS = ('#64748B', '#2563EB', '#D97706', '#059669', '#9333EA', '#DB2777', '#0891B2')


class Persona(Contract):
    kind: Literal['HOST', 'EXPERT']
    name: str
    title: str
    stance: str


class Roster(Contract):
    participants: tuple[Persona, ...]


class Intent(Contract):
    kind: Literal['PASS', 'REQUEST', 'INTERRUPT', 'SUPPLEMENT', 'REBUT']
    target_turn: StrictInt | None = None
    relevance: StrictInt
    public_focus: str


class Utterance(Contract):
    sentences: tuple[str, ...]


class Control(Contract):
    action: Literal['followup', 'linking', 'end']
    public_focus: str


class Point(Contract):
    kind: Literal['consensus', 'disagreement']
    content: str
    source_turns: tuple[StrictInt, ...]
    evidence: tuple['Quote', ...]


class Quote(Contract):
    turn: StrictInt
    quote: str = Field(min_length=1, max_length=400)


Point.model_rebuild()


class Points(Contract):
    items: tuple[Point, ...]


class Summary(Contract):
    content: str


SCHEMAS = dict(roster=Roster, intent=Intent, utterance=Utterance,
               host_control=Control, insights=Points, summary=Summary)


def invalid(issue):
    error=InvalidModelResult()
    error.validation_issue=issue  # Fixed internal code only; never the provider value.
    return error


def missing_configuration(settings):
    if settings.model_provider == 'mock': return []
    if settings.model_provider != 'deepseek': return ['MODEL_PROVIDER']
    missing = [name for name, value in (
        ('MODEL_BASE_URL', settings.model_base_url), ('MODEL_NAME', settings.model_name),
        ('MODEL_API_KEY', settings.model_api_key.get_secret_value()))
        if not value.strip() or '${' in value]
    if settings.model_base_url:
        try:
            parsed = urlsplit(settings.model_base_url)
            parsed.port  # Validate a malformed or out-of-range port without printing the URL.
        except ValueError:
            if 'MODEL_BASE_URL' not in missing: missing.append('MODEL_BASE_URL')
            return missing
        # HTTP is limited to loopback for controlled upstream tests. Never forward keys on redirects.
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (
            parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1'))):
            if 'MODEL_BASE_URL' not in missing: missing.append('MODEL_BASE_URL')
    return missing


@lru_cache(maxsize=7)
def prompt(name):
    return (Path(__file__).parents[1] / 'prompts' / f'{name}.md').read_text(encoding='utf-8')


def public_context(request):
    slots = {p.id: index for index, p in enumerate(request.participants)}
    people = {p.id:p for p in request.participants}
    turns = {m.id: m.turn_no for m in request.messages}
    return {'topic': request.topic, 'expert_count': request.expert_count,
        'participants': [dict(slot=slots[p.id], kind=p.kind, name=p.name, title=p.title, stance=p.stance) for p in request.participants],
        'actor_slot': slots.get(request.actor_id), 'participation_kind': request.participation_kind,
        'target_turn': turns.get(request.target_message_id), 'host_task': request.host_task,
        'public_focus': request.public_focus, 'through_turn': request.through_turn,
        'messages': [dict(turn=m.turn_no, speaker_slot=slots[m.participant_id], speaker_name=people[m.participant_id].name,
            speaker_title=people[m.participant_id].title, speaker_kind=people[m.participant_id].kind,
            content=m.content, kind=m.kind) for m in request.messages],
        'insights': [dict(kind=i.kind, content=i.content, source_turns=[turns[mid] for mid in i.source_message_ids]) for i in request.insights.items]}


def bind_result(request, content):
    """Provider only supplies content and local turn references; backend owns all identities."""
    try:
        parsed = SCHEMAS[request.task].model_validate(json.loads(content))
        raw = parsed.model_dump(); raw['task'] = request.task
        turns = {m.turn_no: m.id for m in request.messages}
        if request.task == 'roster':
            # Normalize host first; preserve expert ordering and assign the existing role palette.
            people = sorted(parsed.participants, key=lambda p: p.kind != 'HOST')
            raw['participants'] = [dict(p.model_dump(), id=uuid5(request.discussion_id, f'{request.roster_revision}:{index}'),
                discussion_id=request.discussion_id, roster_revision=request.roster_revision, color=COLORS[index])
                for index, p in enumerate(people)]
        elif request.task == 'intent':
            target = raw.pop('target_turn')
            raw['target_message_id'] = None if target is None else turns[target]
        elif request.task == 'insights':
            messages={m.turn_no:m for m in request.messages}
            experts={p.id for p in request.participants if p.kind=='EXPERT'}
            for item in parsed.items:
                if len(item.evidence)!=len(item.source_turns) or {q.turn for q in item.evidence}!=set(item.source_turns):
                    raise invalid('evidence_coverage')
                for quote in item.evidence:
                    message=messages[quote.turn]
                    if message.participant_id not in experts or not quote.quote.strip() or quote.quote not in message.content:
                        raise invalid('quote_or_actor_mismatch')
            raw['items'] = [dict(id=uuid5(request.run_id, f'insight:{request.insight_version}:{index}'),
                kind=i.kind, content=i.content, source_message_ids=[turns[t] for t in i.source_turns])
                for index, i in enumerate(parsed.items)]
        return validate_result(request, raw)
    except InvalidModelResult:
        raise
    except ValidationError:
        raise invalid('wire_schema') from None
    except (KeyError, IndexError):
        raise invalid('reference') from None
    except (ValueError, TypeError):
        raise invalid('structure') from None


class DeepSeekGateway:
    def __init__(self, settings, client=None, metrics_sink=None):
        self.settings = settings
        self.owned_client = client is None
        self.client = client or httpx.AsyncClient(timeout=settings.model_timeout_seconds, follow_redirects=False)
        self.metrics = deque(maxlen=2000)  # Safe, bounded observability; never includes prompts, outputs or headers.
        self.metrics_sink = metrics_sink

    async def aclose(self):
        if self.owned_client: await self.client.aclose()

    async def generate(self, request: ModelRequest):
        started = time.monotonic()
        metric = dict(task=request.task, discussion_id=str(request.discussion_id),
            run_id=str(request.run_id) if request.run_id else None, status='pending', usage=None)
        body = dict(model=self.settings.model_name, thinking={'type': 'disabled'},
            response_format={'type': 'json_object'}, stream=False,
            max_tokens=2200 if request.task in ('roster', 'summary', 'insights') else 700,
            messages=[{'role': 'system', 'content': prompt('common') + '\n' + prompt(request.task)},
                      {'role': 'user', 'content': json.dumps(public_context(request), ensure_ascii=False)}])
        try:
            response = await self.client.post(self.settings.model_base_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': 'Bearer ' + self.settings.model_api_key.get_secret_value()}, json=body)
            metric['http_status'] = response.status_code
            if response.status_code != 200:
                code, retryable = {
                    400: ('MODEL_REQUEST_INVALID', False), 422: ('MODEL_REQUEST_INVALID', False),
                    401: ('MODEL_AUTH_FAILED', False), 403: ('MODEL_AUTH_FAILED', False),
                    402: ('MODEL_BALANCE_EXHAUSTED', False), 404: ('MODEL_NOT_FOUND', False),
                    429: ('MODEL_RATE_LIMITED', True), 408: ('MODEL_TIMEOUT', True),
                }.get(response.status_code, ('MODEL_SERVICE_UNAVAILABLE', True) if response.status_code >= 500 else ('MODEL_REQUEST_INVALID', False))
                try: delay = float(response.headers.get('Retry-After', '0.5'))
                except ValueError: delay = .5
                raise ModelServiceError(code, retryable, delay)
            try:
                payload = response.json()
                usage = payload.get('usage')
                if usage is not None and not isinstance(usage,dict): raise InvalidModelResult()
                metric['usage'] = ({k: v for k, v in usage.items() if k in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens') and type(v) is int and v >= 0} or None) if usage else None
                reported=payload.get('model')
                metric['reported_model'] = reported if reported==self.settings.model_name else 'unknown'
                choice = payload['choices'][0]
                if choice['finish_reason'] != 'stop': raise InvalidModelResult()
                # Deliberately never read reasoning_content, including on errors.
                content = choice['message']['content']
                if not isinstance(content, str) or not content.strip(): raise InvalidModelResult()
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                raise InvalidModelResult() from None
            result = bind_result(request, content)
            metric['status'] = 'succeeded'
            return result
        except asyncio.CancelledError:
            metric['status'] = 'cancelled'
            raise
        except httpx.TimeoutException:
            metric['status'] = 'MODEL_TIMEOUT'
            raise ModelServiceError('MODEL_TIMEOUT', True) from None
        except httpx.RequestError:
            metric['status'] = 'MODEL_CONNECTION_FAILED'
            raise ModelServiceError('MODEL_CONNECTION_FAILED', True, .5) from None
        except (ModelServiceError, InvalidModelResult) as exc:
            metric['status'] = str(exc)
            if isinstance(exc, InvalidModelResult): metric['validation_issue']=getattr(exc,'validation_issue','envelope_or_contract')
            raise
        finally:
            metric['duration_ms'] = round((time.monotonic() - started) * 1000, 2)
            self.metrics.append(metric)
            if self.metrics_sink is not None:
                try: self.metrics_sink(dict(metric))
                except Exception: logging.getLogger('panel').warning('model_metrics_export_failed')
