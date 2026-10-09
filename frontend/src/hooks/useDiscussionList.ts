import { useEffect, useState } from 'react'
import { discussionClient } from '../mocks/client'
import type { Discussion } from '../transport/types'

export function useDiscussionList(refresh: number) {
  const [items, setItems] = useState<Discussion[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    setStatus('loading')
    const load = async () => {
      try {
        const result = await discussionClient.list('all', controller.signal)
        if (!alive) return
        setItems(result.items); setStatus('ready')
        timer = setTimeout(load, 1800)
      } catch { if (alive && !controller.signal.aborted) setStatus('failed') }
    }
    void load()
    return () => { alive = false; controller.abort(); clearTimeout(timer) }
  }, [refresh])
  return { items, status }
}
