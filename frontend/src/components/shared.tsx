import type { CSSProperties, ReactNode } from 'react'
import type { DiscussionState, Participant, RoleState } from '../transport/types'

export function Icon({ name, size = 18 }: { name: 'back' | 'arrow' | 'plus' | 'spark' | 'check' | 'message' | 'close' | 'refresh' | 'chevron' | 'grid'; size?: number }) {
  const paths = { back: 'M19 12H5m6-6-6 6 6 6', arrow: 'M5 12h14m-6-6 6 6-6 6', plus: 'M12 5v14M5 12h14', spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z', check: 'm5 12 4 4L19 6', message: 'M4 5h16v12H9l-5 4V5Z', close: 'm6 6 12 12M18 6 6 18', refresh: 'M20 8a8 8 0 1 0 0 8M20 3v5h-5', chevron: 'm8 4 8 8-8 8', grid: 'M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z' }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>
}
export const stateLabels: Record<DiscussionState, string> = { DRAFT: '待生成', GENERATING: '生成阵容中', READY: '待确认阵容', RUNNING: '讨论进行中', SUMMARIZING: '整理总结中', COMPLETED: '讨论已结束', FAILED: '需要处理', INTERRUPTED: '讨论已中断' }
export const roleStyle = (person: Participant): CSSProperties => ({ '--role': person.color } as CSSProperties)
export function Avatar({ person, small = false }: { person: Participant; small?: boolean }) { return <span className={`avatar ${small ? 'small' : ''}`} style={roleStyle(person)}>{person.name.slice(0, 1)}</span> }
export function StateBadge({ state }: { state: DiscussionState }) { return <span className={`state-badge state-${state.toLowerCase()}`}><i />{stateLabels[state]}</span> }
export function Empty({ title, children }: { title: string; children: ReactNode }) { return <div className="empty-state"><span className="empty-icon"><Icon name="message" size={26} /></span><h2>{title}</h2>{children}</div> }
export function PersonCard({ person, status, roster = false }: { person: Participant; status?: RoleState; roster?: boolean }) {
  const state = status?.state ?? 'IDLE'
  return <article className={`person-card ${person.kind === 'HOST' ? 'host-card' : ''} ${state.toLowerCase()}`} style={roleStyle(person)} data-testid={roster ? 'roster-person' : 'expert-card'} data-role-state={state}>
    <div className="person-top"><Avatar person={person} /><div className="person-identity"><h3>{person.name}{person.kind === 'HOST' && <span className="host-label">主持人</span>}</h3><p>{person.title}</p></div>
      {!roster && <span className={`role-status status-${state.toLowerCase()}`}>{state === 'SPEAKING' ? <span className="equalizer"><i /><i /><i /></span> : <i />}{({ IDLE: '待机', PREPARING: '准备发言', SPEAKING: '发言中' })[state]}</span>}
    </div>
    <p className="stance">{person.stance}</p>
    {!roster && <div className="focus"><span>公开关注</span><p>{status?.public_focus || '倾听不同观点，等待合适的回应时机。'}</p></div>}
    {roster && <span className="color-signature"><i style={{ background: person.color }} />专属角色颜色</span>}
  </article>
}
