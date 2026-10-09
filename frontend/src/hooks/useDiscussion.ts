import { useEffect, useState } from 'react'
import { discussionClient, isMockMode } from '../transport/client'
import { projectEvent } from '../transport/projection'
import { ClientError, type ConnectionState, type Snapshot } from '../transport/types'

export function useDiscussion(id: string) {
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [error, setError] = useState<string>()
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    let current: Snapshot | undefined
    let close: (() => void) | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let generation = 0
    let failures = 0
    const controller = new AbortController()
    setSnapshot(previous => previous?.discussion.id === id ? previous : undefined); setError(undefined); setConnection('connecting')
    const recover = (failure: unknown) => {
      if (!alive || timer) return
      ++generation; close?.(); close = undefined
      setConnection('offline')
      setError(failure instanceof Error ? failure.message : '连接中断，正在恢复。')
      if (!isMockMode) timer = setTimeout(() => { timer = undefined; void load() }, Math.min(1000 * 2 ** failures++, 10000))
    }
    const load = async () => {
      const token = ++generation
      try {
      const value = await discussionClient.snapshot(id, controller.signal)
      if (!alive || token !== generation) return
      if (value.discussion.id !== id) throw new ClientError('SNAPSHOT_REQUIRED', '快照讨论归属不匹配。', true)
      current = value; setSnapshot(value)
      setError(undefined)
      if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(value.discussion.state)) { setConnection('live'); return }
      close = discussionClient.subscribe(id, value.last_event_seq, {
        connection: state => { if (alive && token === generation) setConnection(state) },
        failed: failure => { if (alive && token === generation) recover(failure) },
        event: event => {
          if (!alive || token !== generation || !current || event.discussion_id !== id) return
          try {
            current = projectEvent(current, event); setSnapshot(current)
            failures = 0
            if (event.type === 'operation.failed') setError(event.payload.message)
            if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(current.discussion.state)) { close?.(); setConnection('live') }
          } catch (failure) {
            recover(failure)
          }
        },
      })
      } catch (failure) { if (alive && !controller.signal.aborted && token === generation) recover(failure) }
    }
    void load()
    return () => { alive = false; ++generation; clearTimeout(timer); controller.abort(); close?.() }
  }, [id, attempt])
  return { snapshot, connection, error, reconnect: () => setAttempt(n => n + 1), clearError: () => setError(undefined) }
}
