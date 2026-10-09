import fixtureJson from '../../../data/samples/frontend-demo.json'
import { projectEvent } from '../transport/projection'
import { ClientError, type Accepted, type CreateInput, type DiscussionClient, type Observer, type PanelEvent, type Participant, type Snapshot } from '../transport/types'

export const MOCK_STORAGE_KEY = 'ai-panel-studio.frontend-demo.v1'
const fixture = fixtureJson as unknown as { initial: Snapshot; profiles: Participant[]; groups: PanelEvent[][] }
type Listener = { observer: Observer; offline: boolean; closed: boolean }
type MockRecord = { snapshot: Snapshot; people: Participant[]; events: PanelEvent[]; groups: PanelEvent[][]; groupIndex: number; summaryFailure: boolean }
const copy = <T,>(value: T): T => structuredClone(value)
const now = () => new Date().toISOString()

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, ms)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

// The sole owner of prerecorded events, clocks, faults and mock browser storage.
// Replace DiscussionClient at composition time when the real API is ready.
class MockDiscussionClient implements DiscussionClient {
  private records: Record<string, MockRecord> = {}
  private listeners = new Map<string, Set<Listener>>()
  private timers = new Map<string, ReturnType<typeof setTimeout>>()
  private commands = new Map<string, { body: string; result: unknown }>()
  private failList = false
  private failRoster = false
  private failSummary = false
  paused = false
  fast = new URLSearchParams(location.search).get('pace') === 'fast'
  storageAvailable = true

  constructor() {
    try {
      const saved = localStorage.getItem(MOCK_STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved) as Record<string, MockRecord>
        if (Object.values(parsed).every(r => r.snapshot?.discussion?.id && Array.isArray(r.groups) && Array.isArray(r.events))) this.records = parsed
      } else this.seed()
    } catch { this.storageAvailable = false; this.seed() }
    for (const id of Object.keys(this.records)) {
      if (this.records[id].snapshot.discussion.state === 'GENERATING') this.failure(id, 'roster', '模拟阵容准备期间页面已重载，请重新生成。')
      this.records[id].snapshot.insight_status ??= { state: 'IDLE', version: 0, through_turn: 0, error_code: null }
      this.records[id].snapshot.discussion.failure_code ??= null
      this.schedule(id)
    }
  }

  private save() {
    try { localStorage.setItem(MOCK_STORAGE_KEY, JSON.stringify(this.records)) }
    catch { this.storageAvailable = false }
  }
  private record(id: string) {
    const record = this.records[id]
    if (!record) throw new ClientError('DISCUSSION_NOT_FOUND', '这场模拟讨论不存在，请返回讨论列表。')
    return record
  }
  private emit(id: string, type: PanelEvent['type'], payload: PanelEvent['payload'], runId = this.record(id).snapshot.discussion.run_id) {
    const record = this.record(id)
    const event = { schema_version: 1, discussion_id: id, run_id: runId, seq: record.snapshot.last_event_seq + 1, occurred_at: now(), type, payload } as PanelEvent
    record.snapshot = projectEvent(record.snapshot, event)
    record.events.push(copy(event))
    this.save()
    this.listeners.get(id)?.forEach(listener => { if (!listener.closed && !listener.offline) listener.observer.event(copy(event)) })
  }
  private state(id: string, state: Snapshot['discussion']['state'], stage: Snapshot['discussion']['failure_stage'] = null, runId = this.record(id).snapshot.discussion.run_id) {
    this.emit(id, 'discussion.state_changed', { state, version: this.record(id).snapshot.discussion.version + 1, failure_stage: stage }, runId)
  }
  private newRecord(id: string, topic: string, count: number): MockRecord {
    const timestamp = now()
    const people = fixture.profiles.slice(0, count + 1).map(p => ({ ...copy(p), id: crypto.randomUUID(), discussion_id: id }))
    return { snapshot: { discussion: { id, topic, expert_count: count, state: 'DRAFT', version: 0, roster_revision: 0, run_id: null, failure_stage: null, failure_code: null, created_at: timestamp, updated_at: timestamp }, participants: [], role_states: [], messages: [], insights: { version: 0, through_turn: 0, items: [] }, insight_status: { state: 'IDLE', version: 0, through_turn: 0, error_code: null }, summary: null, last_event_seq: 0 }, people, events: [], groups: [], groupIndex: 0, summaryFailure: false }
  }
  private makeGroups(record: MockRecord, runId: string): PanelEvent[][] {
    const roleVersions = new Map<string, number>()
    const map = new Map<string, string>([[fixture.initial.discussion.id, record.snapshot.discussion.id]])
    fixture.profiles.forEach((p, i) => map.set(p.id, record.people[i === 0 ? 0 : 1 + (i - 1) % (record.people.length - 1)].id))
    const remap = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(remap)
      if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, remap(v)]))
      if (typeof value === 'string' && /^[a-f0-9-]{36}$/.test(value)) {
        if (!map.has(value)) map.set(value, crypto.randomUUID())
        return map.get(value)
      }
      return value
    }
    return fixture.groups.map(group => group.map(original => {
      const event = remap(copy(original)) as PanelEvent
      event.discussion_id = record.snapshot.discussion.id
      event.run_id = runId
      if (event.type === 'participant.status_changed') {
        const version = (roleVersions.get(event.payload.participant_id) ?? 0) + 1
        roleVersions.set(event.payload.participant_id, version)
        event.payload.version = version
      }
      if (event.type === 'turn.committed') {
        event.payload.run_id = runId
        event.payload.discussion_id = event.discussion_id
        if (event.payload.turn_no === 1) {
          const topicLabel = [...record.snapshot.discussion.topic.replace(/[。！？!?.\r\n]/g, '，')].slice(0, 140).join('')
          event.payload.content = `今天讨论「${topicLabel}」。我们先比较效率、执行成本和不同岗位的公平。`
        }
      }
      return event
    }))
  }
  private begin(id: string) {
    const record = this.record(id)
    const runId = crypto.randomUUID()
    record.groups = this.makeGroups(record, runId)
    record.groupIndex = 0
    record.summaryFailure = this.failSummary
    this.failSummary = false
    this.state(id, 'RUNNING', null, runId)
  }
  private advance(id: string) {
    const record = this.record(id)
    const group = record.groups[record.groupIndex]
    if (!group) return
    if (record.summaryFailure && group.some(e => e.type === 'summary.ready')) {
      record.summaryFailure = false
      this.failure(id, 'summary', '主持人总结暂时未生成，已保存本场发言和观点。')
      return
    }
    group.forEach(e => e.type === 'discussion.state_changed' ? this.state(id, e.payload.state, e.payload.failure_stage) : this.emit(id, e.type, e.payload))
    record.groupIndex += 1
    this.save()
  }
  private schedule(id: string) {
    if (this.paused || this.timers.has(id)) return
    const record = this.record(id)
    if (!['RUNNING', 'SUMMARIZING'].includes(record.snapshot.discussion.state)) return
    this.timers.set(id, setTimeout(() => {
      this.timers.delete(id)
      this.advance(id)
      this.schedule(id)
    }, this.fast ? 220 : 1200))
  }
  private failure(id: string, stage: 'roster' | 'summary', message: string) {
    this.emit(id, 'operation.failed', { operation_id: crypto.randomUUID(), stage, code: 'MODEL_TIMEOUT', message, retryable: true })
    this.state(id, 'FAILED', stage)
  }
  private async command<T>(scope: string, key: string, body: unknown, action: () => T): Promise<T> {
    await delay(100)
    const signature = JSON.stringify(body)
    const previous = this.commands.get(`${scope}:${key}`)
    if (previous) {
      if (previous.body !== signature) throw new ClientError('IDEMPOTENCY_CONFLICT', '同一操作标识不能用于不同参数。')
      return copy(previous.result as T)
    }
    const result = action()
    this.commands.set(`${scope}:${key}`, { body: signature, result: copy(result) })
    return copy(result)
  }
  async list(status: 'active' | 'all', signal?: AbortSignal) {
    await delay(180, signal)
    if (this.failList) { this.failList = false; throw new ClientError('DATABASE_UNAVAILABLE', '模拟列表暂时无法加载，请重试。', true) }
    const items = Object.values(this.records).map(r => copy(r.snapshot.discussion)).filter(d => status === 'all' || ['RUNNING', 'SUMMARIZING'].includes(d.state)).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
    return { items, next_cursor: null }
  }
  async create(input: CreateInput, key: string) {
    return this.command('create', key, input, () => {
      const topic = input.topic.trim()
      if (!topic || [...topic].length > 500 || !Number.isInteger(input.expert_count) || input.expert_count < 2 || input.expert_count > 6) throw new ClientError('VALIDATION_ERROR', '请填写1–500字的话题，并选择2–6名专家。')
      const id = crypto.randomUUID()
      this.records[id] = this.newRecord(id, topic, input.expert_count)
      this.state(id, 'DRAFT')
      return this.records[id].snapshot
    })
  }
  async generate(id: string, key: string) {
    return this.command(`${id}:generate`, key, {}, () => {
      const record = this.record(id)
      if (!(record.snapshot.discussion.state === 'DRAFT' || (record.snapshot.discussion.state === 'FAILED' && record.snapshot.discussion.failure_stage === 'roster'))) throw new ClientError('INVALID_STATE', '当前状态不能再次生成阵容。')
      const fail = this.failRoster; this.failRoster = false
      this.state(id, 'GENERATING')
      setTimeout(() => {
        if (this.records[id] !== record) return
        if (fail) this.failure(id, 'roster', '嘉宾阵容生成失败，你的话题已保留，可以重新尝试。')
        else {
          this.emit(id, 'roster.ready', { roster_revision: 1, participants: record.people }, null)
          this.state(id, 'READY')
        }
      }, this.fast ? 250 : 1000)
      return { operation_id: crypto.randomUUID(), discussion_id: id, state: 'GENERATING', run_id: null } as Accepted
    })
  }
  async start(id: string, revision: number, key: string) {
    return this.command(`${id}:start`, key, { roster_revision: revision }, () => {
      const record = this.record(id)
      if (revision !== record.snapshot.discussion.roster_revision) throw new ClientError('ROSTER_VERSION_CONFLICT', '阵容版本已变化，请重新查看。')
      if (record.snapshot.discussion.run_id) return { operation_id: record.snapshot.discussion.run_id, discussion_id: id, state: record.snapshot.discussion.state, run_id: record.snapshot.discussion.run_id }
      if (record.snapshot.discussion.state !== 'READY') throw new ClientError('INVALID_STATE', '请等待阵容生成后再确认。')
      this.begin(id); this.schedule(id)
      return { operation_id: crypto.randomUUID(), discussion_id: id, state: 'RUNNING', run_id: record.snapshot.discussion.run_id } as Accepted
    })
  }
  async snapshot(id: string, signal?: AbortSignal) { await delay(90, signal); return copy(this.record(id).snapshot) }
  subscribe(id: string, after: number, observer: Observer) {
    const record = this.record(id)
    const listener: Listener = { observer, offline: false, closed: false }
    observer.connection('connecting')
    const timer = setTimeout(() => {
      if (listener.closed) return
      if (!this.listeners.has(id)) this.listeners.set(id, new Set())
      this.listeners.get(id)!.add(listener)
      record.events.filter(e => e.seq > after).forEach(e => { if (!listener.closed) observer.event(copy(e)) })
      if (!listener.closed) observer.connection('live')
    }, 80)
    return () => { listener.closed = true; clearTimeout(timer); this.listeners.get(id)?.delete(listener) }
  }
  async retrySummary(id: string, key: string) {
    return this.command(`${id}:summary-retry`, key, {}, () => {
      const record = this.record(id)
      if (record.snapshot.discussion.state !== 'FAILED' || record.snapshot.discussion.failure_stage !== 'summary') throw new ClientError('INVALID_STATE', '当前无需重试总结。')
      this.state(id, 'SUMMARIZING')
      this.schedule(id)
      return { operation_id: crypto.randomUUID(), discussion_id: id, state: 'SUMMARIZING', run_id: record.snapshot.discussion.run_id } as Accepted
    })
  }
  disconnect(id: string) { this.listeners.get(id)?.forEach(l => { l.offline = true; l.observer.connection('offline') }) }
  nextRosterFailure() { this.failRoster = true }
  nextSummaryFailure() { this.failSummary = true }
  nextListFailure() { this.failList = true }
  setPaused(value: boolean) {
    this.paused = value
    this.timers.forEach(timer => clearTimeout(timer)); this.timers.clear()
    if (!value) Object.keys(this.records).forEach(id => this.schedule(id))
  }
  private seed() {
    for (const [id, topic] of [['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', fixture.initial.discussion.topic], ['cccccccc-cccc-4ccc-8ccc-cccccccccccc', '混合办公要如何保持协作与公平？']]) {
      this.records[id] = this.newRecord(id, topic, 4)
      this.state(id, 'DRAFT'); this.state(id, 'GENERATING')
      this.emit(id, 'roster.ready', { roster_revision: 1, participants: this.records[id].people }, null)
      this.state(id, 'READY'); this.begin(id)
      while (this.records[id].snapshot.messages.length < 5) this.advance(id)
    }
  }
  reset(empty = false) {
    this.timers.forEach(timer => clearTimeout(timer)); this.timers.clear()
    this.listeners.forEach(set => set.forEach(l => { l.closed = true }))
    this.listeners.clear(); this.commands.clear(); this.records = {}
    this.failList = this.failRoster = this.failSummary = false
    if (!empty) this.seed()
    this.save()
    Object.keys(this.records).forEach(id => this.schedule(id))
  }
}

export const mockControls = new MockDiscussionClient()
export const discussionClient: DiscussionClient = mockControls
