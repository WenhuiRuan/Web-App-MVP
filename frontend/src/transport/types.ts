export type DiscussionState = 'DRAFT' | 'GENERATING' | 'READY' | 'RUNNING' | 'SUMMARIZING' | 'COMPLETED' | 'FAILED' | 'INTERRUPTED'
export type FailureStage = 'roster' | 'discussion' | 'summary'
export type RoleStatus = 'IDLE' | 'PREPARING' | 'SPEAKING'
export interface Participant { id: string; discussion_id: string; roster_revision: number; kind: 'HOST' | 'EXPERT'; name: string; title: string; stance: string; color: string }
export interface RoleState { participant_id: string; state: RoleStatus; public_focus: string; version: number }
export interface Message { id: string; discussion_id: string; run_id: string; participant_id: string; turn_no: number; kind: 'opening' | 'statement' | 'followup' | 'linking'; content: string; created_at: string }
export interface Insight { id: string; kind: 'consensus' | 'disagreement'; content: string; source_message_ids: string[] }
export interface InsightBatch { version: number; through_turn: number; items: Insight[] }
export interface Summary { content: string; through_turn: number; created_at: string }
export interface Discussion { id: string; topic: string; expert_count: number; state: DiscussionState; version: number; roster_revision: number; run_id: string | null; failure_stage: FailureStage | null; created_at: string; updated_at: string }
export interface Snapshot { discussion: Discussion; participants: Participant[]; role_states: RoleState[]; messages: Message[]; insights: InsightBatch; summary: Summary | null; last_event_seq: number }
export interface Failure { operation_id: string; stage: FailureStage; code: string; message: string; retryable: boolean }
export interface StatePayload { state: DiscussionState; version: number; failure_stage: FailureStage | null }
type BaseEvent = { schema_version: 1; discussion_id: string; run_id: string | null; seq: number; occurred_at: string }
export type PanelEvent = BaseEvent & (
  { type: 'discussion.state_changed'; payload: StatePayload } |
  { type: 'roster.ready'; payload: { roster_revision: number; participants: Participant[] } } |
  { type: 'participant.status_changed'; payload: RoleState } |
  { type: 'turn.committed'; payload: Message } |
  { type: 'insights.updated'; payload: InsightBatch } |
  { type: 'summary.ready'; payload: Summary } |
  { type: 'operation.failed'; payload: Failure }
)
export type ConnectionState = 'connecting' | 'live' | 'offline'
export interface CreateInput { topic: string; expert_count: number }
export interface Accepted { operation_id: string; discussion_id: string; state: DiscussionState; run_id: string | null }
export interface Observer { event: (event: PanelEvent) => void; connection: (state: ConnectionState) => void }
export interface DiscussionClient {
  list(status: 'active' | 'all', signal?: AbortSignal): Promise<{ items: Discussion[]; next_cursor: string | null }>
  create(input: CreateInput, key: string): Promise<Snapshot>
  generate(id: string, key: string): Promise<Accepted>
  start(id: string, rosterRevision: number, key: string): Promise<Accepted>
  snapshot(id: string, signal?: AbortSignal): Promise<Snapshot>
  subscribe(id: string, after: number, observer: Observer): () => void
  retrySummary(id: string, key: string): Promise<Accepted>
}
export class ClientError extends Error {
  constructor(public code: string, message: string, public retryable = false) { super(message) }
}
