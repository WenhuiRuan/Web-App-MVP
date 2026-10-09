import { useEffect, useState } from 'react'
import { discussionClient } from '../mocks/client'
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
    const controller = new AbortController()
    setSnapshot(previous => previous?.discussion.id === id ? previous : undefined); setError(undefined); setConnection('connecting')
    discussionClient.snapshot(id, controller.signal).then(value => {
      if (!alive) return
      current = value; setSnapshot(value)
      if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(value.discussion.state)) { setConnection('live'); return }
      close = discussionClient.subscribe(id, value.last_event_seq, {
        connection: state => { if (alive) setConnection(state) },
        event: event => {
          if (!alive || !current || event.discussion_id !== id) return
          try {
            current = projectEvent(current, event); setSnapshot(current)
            if (event.type === 'operation.failed') setError(event.payload.message)
            if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(current.discussion.state)) close?.()
          } catch (failure) {
            close?.(); setConnection('offline')
            setError(failure instanceof ClientError ? failure.message : '事件更新失败，请重新连接。')
          }
        },
      })
    }).catch(failure => { if (alive && !controller.signal.aborted) { setError(failure instanceof Error ? failure.message : '讨论加载失败。'); setConnection('offline') } })
    return () => { alive = false; controller.abort(); close?.() }
  }, [id, attempt])
  return { snapshot, connection, error, reconnect: () => setAttempt(n => n + 1), clearError: () => setError(undefined) }
}
