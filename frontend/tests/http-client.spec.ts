import { test, expect } from '@playwright/test'
import { HttpDiscussionClient, parseEventStream } from '../src/transport/http'

test('SSE parser handles UTF-8 split frames, heartbeat and trailing data', async () => {
  const text = ': heartbeat\r\n\r\nid: a:1\r\nevent: turn.committed\r\ndata: {"value":"中文"}\r\n\r\n'
  const bytes = new TextEncoder().encode(text)
  const body = new ReadableStream<Uint8Array>({ start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close() } })
  const result: unknown[] = []
  await parseEventStream(body, frame => result.push(frame))
  expect(result).toEqual([{ id: 'a:1', type: 'turn.committed', data: { value: '中文' } }])
})

test('HTTP client sends canonical command keys and reports structured failures safely', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  const client = new HttpDiscussionClient(async (url, init) => {
    calls.push({ url: String(url), init })
    return new Response(JSON.stringify({ error: { code: 'INVALID_STATE', message: '需要确认阵容。', retryable: false } }), { status: 409 })
  })
  await expect(client.start('discussion-id', 3, 'command-id')).rejects.toMatchObject({ code: 'INVALID_STATE', message: '需要确认阵容。' })
  expect(calls[0].url).toBe('/api/discussions/discussion-id/start')
  expect(new Headers(calls[0].init?.headers).get('Idempotency-Key')).toBe('command-id')
  expect(calls[0].init?.body).toBe('{"roster_revision":3}')
})

test('closing subscriptions aborts IO and suppresses queued old connection callbacks', async () => {
  let resolve!: (value: Response) => void
  let signal: AbortSignal | undefined
  const client = new HttpDiscussionClient(async (_, init) => {
    signal = init?.signal as AbortSignal
    return await new Promise<Response>(r => { resolve = r })
  })
  const events: unknown[] = []
  const close = client.subscribe('discussion-id', 7, { event: e => events.push(e), connection: () => {}, failed: () => {} })
  close()
  expect(signal?.aborted).toBe(true)
  resolve(new Response('data: {"seq":8}\n\n', { headers: { 'Content-Type': 'text/event-stream' } }))
  await new Promise(r => setTimeout(r, 20))
  expect(events).toEqual([])
})
