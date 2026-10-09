import { ClientError, type Accepted, type CreateInput, type Discussion, type DiscussionClient, type Observer, type PanelEvent, type Snapshot } from './types'

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>
type Frame = { id: string; type: string; data: unknown }
const knownEvents = new Set(['discussion.state_changed', 'roster.ready', 'participant.status_changed', 'turn.committed', 'insights.updated', 'insights.status_changed', 'summary.ready', 'operation.failed'])

export async function parseEventStream(body: ReadableStream<Uint8Array>, receive: (frame: Frame) => void, activity = () => {}) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consume = () => {
    // Normalize only completed CRLF pairs: chunks may end between CR and LF.
    buffer = buffer.replace(/\r\n/g, '\n')
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const lines = buffer.slice(0, boundary).split('\n'); buffer = buffer.slice(boundary + 2)
      const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n')
      if (!data) continue
      const field = (name: string) => lines.find(line => line.startsWith(`${name}:`))?.slice(name.length + 1).trim() ?? ''
      receive({ id: field('id'), type: field('event'), data: JSON.parse(data) })
    }
    if (buffer.length > 262144) throw new ClientError('SSE_INVALID', '事件内容超过允许范围，请重新读取快照。', true)
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) { buffer += decoder.decode(); consume(); break }
      activity(); buffer += decoder.decode(value, { stream: true }); consume()
    }
    if (buffer.trim()) throw new ClientError('SSE_INCOMPLETE', '事件连接在传输途中断开。', true)
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
}

export class HttpDiscussionClient implements DiscussionClient {
  constructor(private fetcher: Fetcher = (input, init) => fetch(input, init)) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const timeout = new AbortController()
    const timer = setTimeout(() => timeout.abort(), 10000)
    try {
      const signal = init.signal ? AbortSignal.any([init.signal, timeout.signal]) : timeout.signal
      const response = await this.fetcher(`/api${path}`, { ...init, signal })
      const value = await response.json().catch(() => null)
      if (!response.ok) throw new ClientError(value?.error?.code ?? 'HTTP_ERROR', value?.error?.message ?? '服务暂时无法完成请求。', value?.error?.retryable ?? response.status >= 500)
      if (!value) throw new ClientError('RESPONSE_INVALID', '服务返回内容不完整。', true)
      return value as T
    } catch (error) {
      if (error instanceof ClientError || init.signal?.aborted) throw error
      throw new ClientError('CONNECTION_FAILED', '无法连接本地后端，请检查服务后重试。', true)
    } finally { clearTimeout(timer) }
  }
  private command<T>(path: string, key: string, body: unknown): Promise<T> {
    return this.request(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body) })
  }
  async list(status: 'active' | 'all', signal?: AbortSignal) {
    const items: Discussion[] = []; let cursor: string | null = null
    do {
      const result: { items: Discussion[]; next_cursor: string | null } = await this.request(`/discussions?status=${status}&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, { signal })
      items.push(...result.items); cursor = result.next_cursor
    } while (cursor)
    return { items, next_cursor: null }
  }
  create(input: CreateInput, key: string) { return this.command<Snapshot>('/discussions', key, input) }
  generate(id: string, key: string) { return this.command<Accepted>(`/discussions/${encodeURIComponent(id)}/roster-generation`, key, {}) }
  start(id: string, revision: number, key: string) { return this.command<Accepted>(`/discussions/${encodeURIComponent(id)}/start`, key, { roster_revision: revision }) }
  snapshot(id: string, signal?: AbortSignal) { return this.request<Snapshot>(`/discussions/${encodeURIComponent(id)}`, { signal }) }
  retrySummary(id: string, key: string) { return this.command<Accepted>(`/discussions/${encodeURIComponent(id)}/summary-retry`, key, {}) }

  subscribe(id: string, after: number, observer: Observer) {
    const controller = new AbortController()
    let active = true
    let lastActivity = Date.now()
    const watchdog = setInterval(() => { if (Date.now() - lastActivity > 40000) controller.abort() }, 1000)
    observer.connection('connecting')
    void (async () => {
      try {
        const response = await this.fetcher(`/api/discussions/${encodeURIComponent(id)}/events?after=${after}`, { headers: { Accept: 'text/event-stream' }, signal: controller.signal })
        if (!active) return
        if (!response.ok) {
          const value = await response.json().catch(() => null)
          throw new ClientError(value?.error?.code ?? 'SSE_FAILED', value?.error?.message ?? '事件连接失败。', true)
        }
        if (!response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) throw new ClientError('SSE_INVALID', '事件连接返回格式不正确。', true)
        observer.connection('live')
        await parseEventStream(response.body, frame => {
          if (!active) return
          const event = frame.data as PanelEvent
          if (!event || !knownEvents.has(frame.type) || frame.type !== event.type || event.discussion_id !== id || !Number.isSafeInteger(event.seq) || event.seq < 1 || frame.id !== `${id}:${event.seq}` || event.schema_version !== 1) throw new ClientError('SSE_INVALID', '事件归属或格式已变化，请恢复快照。', true)
          observer.event(event)
        }, () => { lastActivity = Date.now() })
        // Terminal projection closes before EOF. Unexpected EOF must resnapshot.
        if (active) throw new ClientError('SSE_CLOSED', '事件连接已关闭，正在恢复内容。', true)
      } catch (error) {
        if (active) { observer.connection('offline'); observer.failed?.(error instanceof ClientError ? error : new ClientError('SSE_DISCONNECTED', '连接中断，正在自动恢复。', true)) }
      } finally { clearInterval(watchdog) }
    })()
    return () => { active = false; clearInterval(watchdog); controller.abort() }
  }
}
