"""Stateless Chat Completions adapter. Retry/cancellation budgets belong to the engine."""
import asyncio
import json
import time
import logging
import re
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid5

import httpx
from pydantic import Field, StrictBool, StrictInt, ValidationError

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


class EvidenceChecks(Contract):
    authors_correct: StrictBool
    same_object: StrictBool
    compatible_scope: StrictBool
    every_condition_supported: StrictBool
    explicit_positions: StrictBool
    proposal_preserved: StrictBool
    not_superseded: StrictBool


class PointReview(Contract):
    index: StrictInt
    checks: EvidenceChecks
    content: str = Field(max_length=500)
    source_turns: tuple[StrictInt, ...]
    evidence: tuple[Quote, ...] | None = None
    kind: Literal['consensus','disagreement'] | None = None


class PointsReview(Contract):
    reviews: tuple[PointReview, ...]


class SummaryPosition(Contract):
    speaker_slot: StrictInt
    source_turns: tuple[StrictInt, ...] = Field(min_length=1)
    content: str = Field(min_length=1, max_length=160)


class SummaryPending(Quote):
    issue: Literal['UNANSWERED_QUESTION','UNVERIFIED_PROPOSAL','SCOPE_UNCLEAR','UNIT_OR_DIRECTION_UNCLEAR']


class SummaryReview(Contract):
    introduction: str = Field(min_length=1, max_length=180)
    positions: tuple[SummaryPosition, ...] = Field(max_length=3)
    consensus_indices: tuple[StrictInt, ...]
    disagreement_indices: tuple[StrictInt, ...]
    pending: tuple[SummaryPending, ...] = Field(max_length=2)


def distinct_evidence(items):
    """One rendering per identical kind/source excerpt set; not semantic equivalence."""
    distinct={}
    for item in items:
        key=(item['kind'],tuple(sorted((q['turn'],q['quote'].strip('。！？!? ')) for q in item['evidence'])))
        distinct.setdefault(key,item)
    return list(distinct.values())


def reviewed_summary(request, content):
    try:
        reviewed = SummaryReview.model_validate(json.loads(content))
        messages = {m.turn_no: m for m in request.messages}
        positions = []
        excerpts = set()
        for position in reviewed.positions:
            if not 0 <= position.speaker_slot < len(request.participants): raise invalid('summary_author')
            person = request.participants[position.speaker_slot]
            if person.kind != 'EXPERT' or len(set(position.source_turns)) != len(position.source_turns) or any(
                turn not in messages or messages[turn].participant_id != person.id for turn in position.source_turns):
                raise invalid('summary_author')
            if not any(position.content in messages[turn].content for turn in position.source_turns):
                raise invalid('summary_position_quote')
            if position.content not in excerpts:
                positions.append(person.name + '建议／观点：“' + position.content + '”')
                excerpts.add(position.content)
        def selected(indices, kind):
            if len(set(indices)) != len(indices): raise invalid('summary_insight_reference')
            if any(index < 0 or index >= len(request.insights.items) or request.insights.items[index].kind != kind for index in indices):
                raise invalid('summary_insight_reference')
            return '；'.join(request.insights.items[index].content for index in indices)
        consensus = selected(reviewed.consensus_indices, 'consensus')
        disagreement = selected(reviewed.disagreement_indices, 'disagreement')
        if set(reviewed.consensus_indices)|set(reviewed.disagreement_indices)!=set(range(len(request.insights.items))):
            raise invalid('summary_insight_omission')
        labels = dict(UNANSWERED_QUESTION='尚未回答的问题',UNVERIFIED_PROPOSAL='明确未验证的条件',
            SCOPE_UNCLEAR='范围或前提待核对',UNIT_OR_DIRECTION_UNCLEAR='单位或方向待核对')
        pending=[]
        for item in reviewed.pending:
            if item.turn not in messages or item.quote not in messages[item.turn].content:
                raise invalid('summary_pending_quote')
            if item.issue == 'UNANSWERED_QUESTION' and not re.search(r'[?？]|是否|为何|如何|由谁|哪[个项张类些]|还是|多少|能否|为什么|何时',item.quote):
                raise invalid('summary_question_evidence')
            if any(item.quote in excerpt for excerpt in excerpts): continue
            person=next(p for p in request.participants if p.id==messages[item.turn].participant_id)
            pending.append(f'{labels[item.issue]}（{person.name}第{item.turn}条）：“{item.quote}”')
            excerpts.add(item.quote)
        body = '\n'.join([reviewed.introduction, *(['主要观点：\n' + '\n'.join(positions)] if positions else []),
            '已有共识：' + (consensus or '尚无充分共识。'),
            '未解决分歧：' + (disagreement or '尚无充分证据表明已发生明确分歧。'),
            *(['待澄清：\n' + '\n'.join(pending)] if pending else [])])
        return json.dumps({'content': body}, ensure_ascii=False)
    except InvalidModelResult:
        raise
    except (ValidationError, ValueError, TypeError):
        raise invalid('summary_review_schema') from None


def reviewed_points(request, candidate, content):
    """Review cannot invent sources or people. Failed semantic checks remove the candidate.

    These checks are model judgments, not deterministic proofs of semantic correctness.
    """
    try:
        reviewed = PointsReview.model_validate(json.loads(content))
        indices = [r.index for r in reviewed.reviews]
        if sorted(indices) != list(range(len(candidate['items']))):
            raise invalid('review_coverage')
        messages = {m.turn_no: m for m in request.messages}
        items = []
        for review in sorted(reviewed.reviews, key=lambda r: r.index):
            if not all(review.checks.model_dump().values()): continue
            original = candidate['items'][review.index]
            if len(set(review.source_turns)) != len(review.source_turns) or not set(review.source_turns).issubset(original['source_turns']):
                raise invalid('review_source_expansion')
            actors = {messages[t].participant_id for t in review.source_turns}
            if any(p.id not in actors and p.name in review.content for p in request.participants):
                raise invalid('review_actor_expansion')
            evidence = [q.model_dump() for q in review.evidence] if review.evidence is not None else [q for q in original['evidence'] if q['turn'] in review.source_turns]
            kind=review.kind or original['kind']
            if kind=='disagreement' and not any(re.search(r'反对|反驳|不同意|不赞成|不支持|不接受|不认同|不再认可|不再支持|撤回',q['quote']) for q in evidence):
                continue  # Conservative explicit-opposition gate; implicit alternatives may be omitted.
            if kind == 'consensus':
                joined=r'同时|并记|一并|并行'
                if re.search(joined,review.content) and any(re.search(r'还是|或',q['quote']) and not re.search(joined,q['quote']) for q in evidence):
                    continue  # A choice expression alone cannot prove joint adoption.
                # Conservative lexical provenance, not a semantic agreement detector.
                # Explicit support counts describe bound authors, not a proposed staffing
                # condition. Verify these counts directly, then check other quantities.
                support_counts=re.findall(r'(\d+|[一二三四五六两])(?:位专家|人)(?:的)?(?:共同|一致|均|都)',review.content)
                numerals={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6}
                if any((int(n) if n.isdigit() else numerals[n])!=len(actors) for n in support_counts): continue
                conditions=re.sub(r'(\d+|[一二三四五六两])(?:位专家|人)(?:的)?(?:共同|一致|均|都)','',review.content)
                quantities = re.findall(r'(?:\d+(?:\.\d+)?|[一二三四五六七八九十百千万两]+)(?:%|个?工作日|个?自然周|周|天|小时|分钟|成|人|次)', conditions)
                if any(quantity not in quote['quote'] for quantity in quantities for quote in evidence):
                    continue  # Exclude this unsupported claim without discarding other candidates.
            names=[p.name for p in request.participants if p.id in actors]
            text=review.content if all(name in review.content for name in names) else '与'.join(names)+'：'+review.content
            items.append(dict(original, kind=kind, content=text, source_turns=list(review.source_turns),
                evidence=evidence))
        unique={}
        for item in items:
            key=(item['kind'],item['content'],tuple(sorted(item['source_turns'])))
            unique.setdefault(key,item)
        return json.dumps({'items': distinct_evidence(list(unique.values()))}, ensure_ascii=False)
    except InvalidModelResult:
        raise
    except (ValidationError, ValueError, TypeError):
        raise invalid('review_schema') from None


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


@lru_cache(maxsize=9)
def prompt(name):
    return (Path(__file__).parents[1] / 'prompts' / f'{name}.md').read_text(encoding='utf-8')


def public_context(request):
    slots = {p.id: index for index, p in enumerate(request.participants)}
    people = {p.id:p for p in request.participants}
    turns = {m.id: m.turn_no for m in request.messages}
    def public_message(message):
        person = people[message.participant_id]
        return dict(turn=message.turn_no, speaker_slot=slots[person.id], speaker_name=person.name,
                    speaker_title=person.title, speaker_kind=person.kind, content=message.content, kind=message.kind)
    messages = {m.id: public_message(m) for m in request.messages}
    # Personas guide an actor, but are never evidence of an expressed opinion.
    participants = [dict(slot=slots[p.id], kind=p.kind, name=p.name, title=p.title,
        **({'stance': p.stance} if request.task in ('intent', 'utterance') else {})) for p in request.participants]
    return {'task': request.task, 'topic': request.topic, 'expert_count': request.expert_count,
        'participants': participants,
        'actor_slot': slots.get(request.actor_id), 'participation_kind': request.participation_kind,
        'target_turn': turns.get(request.target_message_id), 'host_task': request.host_task,
        'target_message': messages.get(request.target_message_id), 'focus_is_unverified': request.task == 'utterance',
        'public_focus': request.public_focus, 'through_turn': request.through_turn,
        'previous_through_turn': request.insights.through_turn if request.task=='insights' else None,
        'messages': [m for m in messages.values() if request.task != 'insights' or m['speaker_kind'] == 'EXPERT'],
        'insights': [dict(index=index, kind=i.kind, content=i.content, source_turns=[turns[mid] for mid in i.source_message_ids],
            semantic_status='candidate_requires_transcript_review',
            sources=[messages[mid] for mid in i.source_message_ids]) for index, i in enumerate(request.insights.items)]}


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
    multi_step_synthesis = True  # Individual HTTP timeout below; engine owns the total task deadline.
    def __init__(self, settings, client=None, metrics_sink=None):
        self.settings = settings
        self.owned_client = client is None
        self.client = client or httpx.AsyncClient(timeout=settings.model_timeout_seconds, follow_redirects=False)
        self.metrics = deque(maxlen=2000)  # Safe, bounded observability; never includes prompts, outputs or headers.
        self.metrics_sink = metrics_sink

    async def aclose(self):
        if self.owned_client: await self.client.aclose()

    async def generate(self, request: ModelRequest):
        context = public_context(request)
        synthesis = request.task in ('insights', 'summary')
        result, final = await self._complete(request, context, 'draft' if synthesis else 'single')
        if synthesis:
            # A new stateless request sees the original evidence and an explicitly untrusted
            # candidate, never a shared chat or hidden reasoning. Only reviewed output leaves.
            candidate = json.loads(final)
            if request.task == 'insights':
                # Prior points are review candidates, never silently unioned into output.
                # Recheck the whole current prefix for withdrawal/changed conditions.
                messages={m.turn_no:m for m in request.messages}
                for previous in context['insights']:
                    turns=previous['source_turns']
                    candidate['items'].append(dict(kind=previous['kind'],content=previous['content'],source_turns=turns,
                        evidence=[dict(turn=t,quote=messages[t].content[:400]) for t in turns]))
                unique={}
                for item in candidate['items']:
                    key=(item['kind'],item['content'],tuple(sorted(item['source_turns'])))
                    unique.setdefault(key,item)
                candidate['items']=list(unique.values())
            if request.task=='insights' and candidate['items']:
                reviewed=[]; valid_reviews=0; failure=None
                for index,item in enumerate(candidate['items']):
                    sources=set(item['source_turns'])
                    actors={m.participant_id for m in request.messages if m.turn_no in sources}
                    boundary=max(sources)
                    focused=[m for m in context['messages'] if m['turn'] in sources or
                        (m['turn']>boundary and request.participants[m['speaker_slot']].id in actors)]
                    try:
                        _, final_point=await self._complete(request,dict(context,messages=focused,insights=[],
                            candidate={'items':[item]},review_origin_index=index),'review')
                    except InvalidModelResult as exc:
                        failure=exc
                        continue  # Never publish this candidate; other independent reviews remain valid.
                    valid_reviews+=1
                    reviewed.extend(json.loads(final_point)['items'])
                if failure is not None and not valid_reviews: raise failure
                unique={}
                for item in reviewed:
                    unique.setdefault((item['kind'],item['content'],tuple(sorted(item['source_turns']))),item)
                return bind_result(request,json.dumps({'items':distinct_evidence(list(unique.values()))},ensure_ascii=False))
            result, _ = await self._complete(request, dict(context, candidate=candidate), 'review')
        return result

    async def _complete(self, request, context, stage):
        started = time.monotonic()
        metric = dict(task=request.task, discussion_id=str(request.discussion_id),
            run_id=str(request.run_id) if request.run_id else None, stage=stage, status='pending', usage=None)
        if 'review_origin_index' in context: metric['review_index']=context['review_origin_index']
        body = dict(model=self.settings.model_name, thinking={'type': self.settings.model_thinking_mode},
            response_format={'type': 'json_object'}, stream=False,
            max_tokens=2200 if request.task in ('roster', 'summary', 'insights') else 700,
            messages=[{'role': 'system', 'content': prompt('common') + '\n' +
                       prompt(request.task + '_review' if stage == 'review' else request.task)},
                      {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}])
        if self.settings.model_thinking_mode == 'enabled':
            body.update(reasoning_effort=self.settings.model_reasoning_effort,
                max_tokens=self.settings.model_thinking_max_tokens)
        try:
            response = await self.client.post(self.settings.model_base_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': 'Bearer ' + self.settings.model_api_key.get_secret_value()}, json=body,
                timeout=self.settings.model_timeout_seconds)
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
            if stage == 'review':
                content = reviewed_points(request, context['candidate'], content) if request.task == 'insights' else reviewed_summary(request, content)
            if stage=='draft' and request.task=='insights':
                try:
                    parsed=Points.model_validate(json.loads(content))
                except ValidationError:
                    raise invalid('wire_schema') from None
                except (ValueError,TypeError):
                    raise invalid('structure') from None
                safe=[]; failure=None
                for item in parsed.items:
                    try:
                        bind_result(request,json.dumps({'items':[item.model_dump()]},ensure_ascii=False))
                        safe.append(item.model_dump())
                    except InvalidModelResult as exc:
                        failure=exc
                metric['discarded_candidates']=len(parsed.items)-len(safe)
                if failure is not None and not safe and not request.insights.items: raise failure
                content=json.dumps({'items':safe},ensure_ascii=False)
            result = bind_result(request, content)
            metric['status'] = 'succeeded'
            return result, content
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
