"""Versioned public contracts and provider-independent structured output shapes."""
import re
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field,
                      StrictInt, StringConstraints, TypeAdapter, model_validator)


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, hide_input_in_errors=True, frozen=True)


Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
Positive = Annotated[StrictInt, Field(ge=1)]
Nonnegative = Annotated[StrictInt, Field(ge=0)]
State = Literal['DRAFT', 'GENERATING', 'READY', 'RUNNING', 'SUMMARIZING', 'COMPLETED', 'FAILED', 'INTERRUPTED']
FailureStage = Literal['roster', 'discussion', 'summary']
RoleStatus = Literal['IDLE', 'PREPARING', 'SPEAKING']


def validate_sentence(value: str) -> str:
    pieces = [p.strip() for p in re.split(r'[。！？!?]+|(?<!\d)\.(?!\d)', value) if p.strip()]
    if len(pieces) != 1:
        raise ValueError('expected one sentence')
    return value


Sentence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(validate_sentence)]


class CreateDiscussion(Contract):
    topic: Topic
    expert_count: Annotated[StrictInt, Field(ge=2, le=6)] = 4


class StartDiscussion(Contract):
    roster_revision: Positive


class EmptyCommand(Contract):
    pass


class Participant(Contract):
    id: UUID
    discussion_id: UUID
    roster_revision: Positive = 1
    kind: Literal['HOST', 'EXPERT']
    name: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    stance: ShortText
    color: Annotated[str, StringConstraints(pattern=r'^#[0-9A-F]{6}$')]


def check_roster(people: tuple[Participant, ...], expected_experts: int | None = None) -> None:
    if not 3 <= len(people) <= 7 or sum(p.kind == 'HOST' for p in people) != 1:
        raise ValueError('roster requires one host and 2-6 experts')
    if expected_experts is not None and len(people) != expected_experts + 1:
        raise ValueError('roster count mismatch')
    for field in ('id', 'name', 'color'):
        if len({getattr(p, field) for p in people}) != len(people):
            raise ValueError('duplicate roster identity')


class RoleState(Contract):
    participant_id: UUID
    state: RoleStatus
    public_focus: Annotated[str, StringConstraints(max_length=140)] = ''
    version: Nonnegative = 0


class Message(Contract):
    id: UUID
    discussion_id: UUID
    run_id: UUID
    participant_id: UUID
    turn_no: Positive
    kind: Literal['opening', 'statement', 'followup', 'linking']
    content: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    created_at: AwareDatetime

    @model_validator(mode='after')
    def short_content(self) -> Self:
        parts = [p.strip() for p in re.split(r'[。！？!?]+|(?<!\d)\.(?!\d)', self.content) if p.strip()]
        if not 1 <= len(parts) <= 2:
            raise ValueError('expected 1-2 sentences')
        return self


class Insight(Contract):
    id: UUID
    kind: Literal['consensus', 'disagreement']
    content: Topic
    source_message_ids: Annotated[tuple[UUID, ...], Field(min_length=1)]

    @model_validator(mode='after')
    def distinct_sources(self) -> Self:
        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError('duplicate source')
        return self


class InsightBatch(Contract):
    version: Nonnegative = 0
    through_turn: Nonnegative = 0
    items: tuple[Insight, ...] = ()


def validate_insight_evidence(participants, messages, items):
    experts = {p.id for p in participants if p.kind == 'EXPERT'}
    by_id = {m.id:m for m in messages}
    if len({i.id for i in items}) != len(items):
        raise ValueError('duplicate insight')
    for item in items:
        if not set(item.source_message_ids) <= by_id.keys():
            raise ValueError('unknown source')
        actors = {by_id[source].participant_id for source in item.source_message_ids} & experts
        if len(actors) < 2:
            raise ValueError('evidence requires two distinct experts')


class InsightStatus(Contract):
    state: Literal['IDLE','PENDING','SUCCEEDED','FAILED','INTERRUPTED'] = 'IDLE'
    version: Nonnegative = 0
    through_turn: Nonnegative = 0
    error_code: str | None = None


def validate_natural_summary(value: str) -> str:
    if '```' in value or value.startswith(('{','[')):
        raise ValueError('summary cannot contain structured output or code blocks')
    try:
        json.loads(value)
    except ValueError:
        return value
    raise ValueError('summary cannot be raw JSON')


NaturalSummary = Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=4000),AfterValidator(validate_natural_summary)]


class Summary(Contract):
    content: NaturalSummary
    through_turn: Nonnegative
    created_at: AwareDatetime


class Discussion(Contract):
    id: UUID
    topic: Topic
    expert_count: Annotated[StrictInt, Field(ge=2, le=6)]
    state: State
    version: Nonnegative
    roster_revision: Nonnegative
    run_id: UUID | None
    failure_stage: FailureStage | None = None
    failure_code: Annotated[str, StringConstraints(max_length=64)] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Snapshot(Contract):
    discussion: Discussion
    participants: tuple[Participant, ...] = ()
    role_states: tuple[RoleState, ...] = ()
    messages: tuple[Message, ...] = ()
    insights: InsightBatch = Field(default_factory=InsightBatch)
    insight_status: InsightStatus = Field(default_factory=InsightStatus)
    summary: Summary | None = None
    last_event_seq: Nonnegative

    @model_validator(mode='after')
    def consistent_projection(self) -> Self:
        d = self.discussion
        if self.participants or d.state in ('READY', 'RUNNING', 'SUMMARIZING', 'COMPLETED'):
            check_roster(self.participants, d.expert_count)
        ids = {p.id for p in self.participants}
        if len(ids) != len(self.participants):
            raise ValueError('duplicate participant')
        if any(p.discussion_id != d.id or p.roster_revision != d.roster_revision for p in self.participants):
            raise ValueError('participant scope mismatch')
        if any(m.discussion_id != d.id or m.run_id != d.run_id or m.participant_id not in ids for m in self.messages):
            raise ValueError('message scope mismatch')
        if [m.turn_no for m in self.messages] != list(range(1, len(self.messages) + 1)):
            raise ValueError('message sequence gap')
        if len({m.id for m in self.messages}) != len(self.messages):
            raise ValueError('duplicate message')
        if any(s.participant_id not in ids for s in self.role_states) or len({s.participant_id for s in self.role_states}) != len(self.role_states):
            raise ValueError('role state scope mismatch')
        if sum(s.state == 'SPEAKING' for s in self.role_states) > 1:
            raise ValueError('multiple speakers')
        sources = {m.id for m in self.messages if m.turn_no <= self.insights.through_turn}
        if self.insights.through_turn > len(self.messages) or any(not set(i.source_message_ids) <= sources for i in self.insights.items):
            raise ValueError('invalid insight source')
        validate_insight_evidence(self.participants, self.messages, self.insights.items)
        if self.summary and self.summary.through_turn != len(self.messages):
            raise ValueError('summary boundary mismatch')
        if d.state == 'COMPLETED' and self.summary is None:
            raise ValueError('completed without summary')
        return self


class DiscussionList(Contract):
    items: tuple[Discussion, ...]
    next_cursor: str | None = None


class OperationAccepted(Contract):
    operation_id: UUID
    discussion_id: UUID
    state: State
    run_id: UUID | None = None


class Operation(Contract):
    id: UUID
    discussion_id: UUID | None
    kind: Literal['create', 'roster-generation', 'start', 'summary-retry']
    status: Literal['ACCEPTED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED']
    error_code: str | None = None


class ErrorDetail(Contract):
    field: str
    reason: str


class ErrorBody(Contract):
    code: str
    message: str
    retryable: bool
    request_id: UUID
    details: tuple[ErrorDetail, ...] = ()


class ErrorResponse(Contract):
    error: ErrorBody


class StatePayload(Contract):
    state: State
    version: Nonnegative
    failure_stage: FailureStage | None = None
    failure_code: str | None = None


class RosterPayload(Contract):
    roster_revision: Positive
    participants: tuple[Participant, ...]

    @model_validator(mode='after')
    def valid_roster(self) -> Self:
        check_roster(self.participants)
        return self


class FailurePayload(Contract):
    operation_id: UUID
    stage: FailureStage
    code: str
    message: str
    retryable: bool


class EventBase(Contract):
    schema_version: Literal[1] = 1
    discussion_id: UUID
    run_id: UUID | None
    seq: Positive
    occurred_at: AwareDatetime


class StateEvent(EventBase):
    type: Literal['discussion.state_changed']
    payload: StatePayload


class RosterEvent(EventBase):
    type: Literal['roster.ready']
    payload: RosterPayload

    @model_validator(mode='after')
    def roster_scope(self) -> Self:
        if self.run_id is not None or any(p.discussion_id != self.discussion_id or p.roster_revision != self.payload.roster_revision for p in self.payload.participants):
            raise ValueError('roster event scope mismatch')
        return self


class RunEvent(EventBase):
    run_id: UUID


class RoleEvent(RunEvent):
    type: Literal['participant.status_changed']
    payload: RoleState


class TurnEvent(RunEvent):
    type: Literal['turn.committed']
    payload: Message

    @model_validator(mode='after')
    def turn_scope(self) -> Self:
        if self.payload.discussion_id != self.discussion_id or self.payload.run_id != self.run_id:
            raise ValueError('turn event scope mismatch')
        return self


class InsightsEvent(RunEvent):
    type: Literal['insights.updated']
    payload: InsightBatch


class InsightStatusEvent(RunEvent):
    type: Literal['insights.status_changed']
    payload: InsightStatus


class SummaryEvent(RunEvent):
    type: Literal['summary.ready']
    payload: Summary


class FailureEvent(EventBase):
    type: Literal['operation.failed']
    payload: FailurePayload


Event = Annotated[StateEvent | RosterEvent | RoleEvent | TurnEvent | InsightsEvent | InsightStatusEvent | SummaryEvent | FailureEvent, Field(discriminator='type')]
EventAdapter = TypeAdapter(Event)


class ModelRequest(Contract):
    task: Literal['roster', 'intent', 'utterance', 'host_control', 'insights', 'summary']
    discussion_id: UUID
    run_id: UUID | None = None
    topic: Topic
    expert_count: Annotated[StrictInt, Field(ge=2, le=6)] = 4
    roster_revision: Positive = 1
    actor_id: UUID | None = None
    participants: tuple[Participant, ...] = ()
    messages: tuple[Message, ...] = ()
    cycle: Nonnegative = 0
    participation_kind: Literal['REQUEST','INTERRUPT','SUPPLEMENT','REBUT'] | None = None
    target_message_id: UUID | None = None
    host_task: Literal['opening','followup','linking'] | None = None
    public_focus: Annotated[str, StringConstraints(max_length=140)] = ''

    through_turn: Nonnegative | None = None
    insight_version: Positive | None = None
    insights: InsightBatch = Field(default_factory=InsightBatch)

    @model_validator(mode='after')
    def context_scope(self) -> Self:
        ids = {p.id for p in self.participants}
        if any(p.discussion_id != self.discussion_id or p.roster_revision != self.roster_revision for p in self.participants):
            raise ValueError('participant context mismatch')
        if any(m.discussion_id != self.discussion_id or m.run_id != self.run_id or m.participant_id not in ids for m in self.messages):
            raise ValueError('message context mismatch')
        if self.task != 'roster' and (self.run_id is None or not ids):
            raise ValueError('run and participants required')
        if self.task != 'roster':
            check_roster(self.participants, self.expert_count)
        if self.task in ('intent', 'utterance', 'host_control') and self.actor_id not in ids:
            raise ValueError('actor required in roster')
        actor = next((p for p in self.participants if p.id == self.actor_id), None)
        if self.task in ('intent','utterance','host_control') and self.cycle < 1:
            raise ValueError('positive cycle required')
        if self.task == 'utterance':
            if actor.kind == 'HOST':
                if self.host_task is None or self.participation_kind or self.target_message_id:
                    raise ValueError('host utterance requires only host task')
            elif self.participation_kind is None or self.host_task:
                raise ValueError('expert utterance requires participation type')
            if self.participation_kind in ('SUPPLEMENT','REBUT') and self.target_message_id is None:
                raise ValueError('response target required')
            if self.target_message_id and not any(m.id == self.target_message_id and m.participant_id != self.actor_id for m in self.messages):
                raise ValueError('invalid response target')
        elif self.host_task or self.participation_kind or self.target_message_id or self.public_focus:
            raise ValueError('utterance context belongs only to utterance')
        if self.task == 'intent' and (actor is None or actor.kind != 'EXPERT'):
            raise ValueError('only experts submit intents')
        if self.task == 'host_control' and (actor is None or actor.kind != 'HOST'):
            raise ValueError('host control requires a host')
        if len({m.id for m in self.messages}) != len(self.messages) or any(a.turn_no >= b.turn_no for a, b in zip(self.messages, self.messages[1:])):
            raise ValueError('context messages must be unique and ordered')
        if self.task == 'roster' and (self.run_id or self.messages or self.participants or self.actor_id):
            raise ValueError('roster generation has no existing run context')
        if self.task == 'insights':
            if self.through_turn is None or self.insight_version is None:
                raise ValueError('insights require boundary and version')
            if [m.turn_no for m in self.messages] != list(range(1,self.through_turn+1)):
                raise ValueError('insights require full frozen prefix')
        elif self.task == 'summary':
            if self.through_turn is None or self.insight_version is not None or actor is None or actor.kind != 'HOST':
                raise ValueError('summary requires host and boundary')
            if [m.turn_no for m in self.messages] != list(range(1,self.through_turn+1)):
                raise ValueError('summary requires full frozen prefix')
            if self.insights.through_turn>self.through_turn:
                raise ValueError('summary insights beyond boundary')
            validate_insight_evidence(self.participants,tuple(m for m in self.messages if m.turn_no<=self.insights.through_turn),self.insights.items)
        elif self.insight_version is not None or self.through_turn is not None:
            raise ValueError('extraction fields belong to insights')
        if self.task!='summary' and self.insights!=InsightBatch():
            raise ValueError('summary insights belong only to summary')
        return self


class RosterResult(Contract):
    task: Literal['roster']
    participants: tuple[Participant, ...]

    @model_validator(mode='after')
    def valid_roster(self) -> Self:
        check_roster(self.participants)
        return self


class IntentResult(Contract):
    task: Literal['intent']
    kind: Literal['PASS', 'REQUEST', 'INTERRUPT', 'SUPPLEMENT', 'REBUT']
    target_message_id: UUID | None = None
    relevance: Annotated[StrictInt, Field(ge=0, le=100)]
    public_focus: ShortText


class UtteranceResult(Contract):
    task: Literal['utterance']
    sentences: Annotated[tuple[Sentence, ...], Field(min_length=1, max_length=2)]


class HostControlResult(Contract):
    task: Literal['host_control']
    action: Literal['followup', 'linking', 'end']
    public_focus: ShortText


class InsightsResult(Contract):
    task: Literal['insights']
    items: tuple[Insight, ...]


class SummaryResult(Contract):
    task: Literal['summary']
    content: NaturalSummary


ModelResult = Annotated[RosterResult | IntentResult | UtteranceResult | HostControlResult | InsightsResult | SummaryResult, Field(discriminator='task')]
ModelResultAdapter = TypeAdapter(ModelResult)


class ContractExamples(Contract):
    create: CreateDiscussion
    start: StartDiscussion
    accepted: OperationAccepted
    snapshot: Snapshot
    listing: DiscussionList
    operation: Operation
    error: ErrorResponse
    events: tuple[Event, ...]
    model_request: ModelRequest
    model_requests: tuple[ModelRequest,...] = ()
    model_results: tuple[ModelResult, ...]
