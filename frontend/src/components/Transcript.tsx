import { isMockMode } from '../transport/client'
import { useLayoutEffect, useRef, useState } from 'react'
import type { Snapshot } from '../transport/types'
import { Avatar, Empty } from './shared'

export function Transcript({ snapshot, focusId, visible }: { snapshot: Snapshot; focusId?: string; visible: boolean }) {
  const scroll = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const [readThrough, setReadThrough] = useState(snapshot.messages.length)
  const count = snapshot.messages.length
  useLayoutEffect(() => {
    const box = scroll.current
    if (box && atBottom.current) { box.scrollTop = box.scrollHeight; setReadThrough(count) }
  }, [count, visible])
  useLayoutEffect(() => {
    if (!focusId || !visible) return
    const item = scroll.current?.querySelector<HTMLElement>(`[data-message-id="${focusId}"]`)
    if (item) { atBottom.current = false; item.scrollIntoView({ block: 'center', behavior: 'auto' }); item.focus({ preventScroll: true }) }
  }, [focusId, visible])
  const updatePosition = () => {
    const box = scroll.current
    if (!box) return
    atBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 48
    if (atBottom.current) setReadThrough(count)
  }
  return <section className={`panel transcript-panel ${visible ? 'mobile-visible' : ''}`} aria-label="现场发言区域">
    <div className="panel-heading"><div><span className="section-kicker">LIVE TRANSCRIPT</span><h2>现场 Transcript</h2></div><span className="count-badge">{count.toString().padStart(2, '0')} 条</span></div>
    <div className="transcript-scroll" data-testid="transcript-scroll" ref={scroll} onScroll={updatePosition} tabIndex={0} aria-label="正式发言记录">
      {!count && <Empty title="等待主持人开场"><p>正式发言将出现在这里。嘉宾状态与公开关注点会随讨论更新。</p></Empty>}
      {snapshot.messages.map(message => {
        const person = snapshot.participants.find(p => p.id === message.participant_id)!
        const speaking = snapshot.role_states.some(s => s.participant_id === person.id && s.state === 'SPEAKING') && message.turn_no === count
        return <article key={message.id} className={`message-row ${speaking ? 'current-message' : ''} ${focusId === message.id ? 'cited-message' : ''}`} data-testid="message" data-message-id={message.id} tabIndex={-1} style={{ '--role': person.color } as React.CSSProperties}>
          <Avatar person={person} small /><div className="message-body"><div className="message-meta"><strong>{person.name}</strong><span>{person.title}</span><b className="turn-no">#{message.turn_no.toString().padStart(2, '0')}</b></div>
            {speaking && <span className="speaking-label">正在发言</span>}<p>{message.content}</p></div>
        </article>
      })}
    </div>
    {!atBottom.current && count > readThrough && <button className="new-messages" onClick={() => { atBottom.current = true; if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; setReadThrough(count) }}>{count - readThrough} 条新发言 · 回到现场 ↓</button>}
    <div className="panel-footer"><span className="record-dot" />仅记录正式发言<span className="subtle">{isMockMode ? '预设演示内容' : '后端已提交内容'}</span></div>
  </section>
}
