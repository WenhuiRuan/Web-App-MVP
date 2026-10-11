import { useEffect, useRef, useState } from 'react'
import { useDiscussion } from '../hooks/useDiscussion'
import { discussionClient, isMockMode } from '../transport/client'
import type { Discussion, Snapshot } from '../transport/types'
import { Empty, Icon, PersonCard, StateBadge } from '../components/shared'
import { Transcript } from '../components/Transcript'
import { Insights, SummaryText } from '../components/Insights'

function TopicDialog({ topic, close }: { topic: string; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    element?.showModal()
    return () => { element?.close(); if (trigger?.isConnected) trigger.focus({ preventScroll: true }) }
  }, [])
  return <dialog ref={dialog} onCancel={close} aria-label="完整话题" className="summary-dialog topic-dialog"><div className="dialog-heading"><h2>完整话题</h2><button className="icon-button" aria-label="关闭完整话题" onClick={close}><Icon name="close" /></button></div><div className="dialog-body"><p>{topic}</p></div></dialog>
}

function SummaryDialog({ snapshot, close }: { snapshot: Snapshot; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    element?.showModal()
    return () => { element?.close(); if (trigger?.isConnected) trigger.focus({ preventScroll: true }) }
  }, [])
  return <dialog ref={dialog} onCancel={close} aria-label="主持人总结" className="summary-dialog"><div className="dialog-heading"><div><span className="section-kicker">THE ROUND TABLE, RECAP</span><h2>主持人总结</h2></div><button className="icon-button" aria-label="关闭总结" onClick={close}><Icon name="close" /></button></div><div className="dialog-body"><h3>{snapshot.discussion.topic}</h3><SummaryText snapshot={snapshot} /></div><div className="dialog-footer"><span>{isMockMode ? '本场内容已保存在浏览器中' : '本场内容已保存在本地数据库中'}</span><button className="primary" onClick={close}>返回讨论现场</button></div></dialog>
}

export function Room({ id, items, navigate }: { id: string; items: Discussion[]; navigate: (path: string) => void }) {
  const { snapshot, connection, error, reconnect, clearError } = useDiscussion(id)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string>()
  const [mobileTab, setMobileTab] = useState('transcript')
  const [focusId, setFocusId] = useState<string>()
  const [showSummary, setShowSummary] = useState(false)
  const [showTopic, setShowTopic] = useState(false)
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setActionError(undefined); clearError()
    try { await action(); reconnect() } catch (e) { setActionError(e instanceof Error ? e.message : '操作失败，请重试。') }
    finally { setBusy(false) }
  }
  if (!snapshot) return <div className="scroll-page"><button className="back-button" onClick={() => navigate('/')}>← 返回讨论列表</button>{error ? <Empty title="讨论加载失败"><p>{error}</p><button className="secondary" onClick={reconnect}>重试加载</button></Empty> : <div className="loading-room" role="status"><div className="skeleton" /><p>正在打开这场圆桌…</p></div>}</div>
  const d = snapshot.discussion
  const preparing = ['DRAFT', 'GENERATING', 'READY'].includes(d.state) || (['FAILED', 'INTERRUPTED'].includes(d.state) && d.failure_stage === 'roster')
  if (preparing) return <div className="scroll-page roster-page"><button className="back-button" onClick={() => navigate('/')}>← 返回讨论列表</button><span className="section-kicker">MEET YOUR PANEL</span><h1>{d.state === 'READY' ? '确认这场圆桌的阵容' : d.state === 'FAILED' ? '嘉宾阵容暂未就绪' : '正在邀请不同视角…'}</h1><p className="roster-topic">{d.topic}</p><div className="roster-meta"><StateBadge state={d.state} /><span>1 位主持人 + {d.expert_count} 位专家 · {isMockMode ? '预设模拟阵容' : '后端生成阵容'}</span></div>{connection === 'offline' && <div className="alert warning" role="alert"><span>连接中断，阵容内容已保留，正在自动恢复。</span><button onClick={reconnect}>重新连接</button></div>}{actionError && <div className="alert error" role="alert">{actionError}</div>}{d.state === 'READY' ? <><div className="roster-grid">{snapshot.participants.map(p => <PersonCard key={p.id} person={p} roster />)}</div><div className="roster-confirm"><p>主持人负责串联，专家以各自立场展开补充与回应。<br />确认后由后端独立推进本场讨论。</p><button className="primary" disabled={busy} onClick={() => void act(() => discussionClient.start(id, d.roster_revision, crypto.randomUUID()))}><Icon name="check" />{busy ? '正在进入…' : '确认阵容，进入演播厅'}</button></div></> : ['FAILED', 'INTERRUPTED', 'DRAFT'].includes(d.state) ? <Empty title={d.state === 'FAILED' ? '生成失败，话题已保留' : '准备生成嘉宾阵容'}><p>{error || '你可以使用同一个话题重新生成阵容。'}</p><button className="primary" disabled={busy} onClick={() => void act(() => discussionClient.generate(id, crypto.randomUUID()))}>重新生成阵容</button></Empty> : <div className="roster-grid" role="status" aria-label="嘉宾阵容生成中">{Array.from({ length: d.expert_count + 1 }, (_, i) => <div key={i} className="skeleton roster-skeleton" />)}</div>}</div>
  const host = snapshot.participants.find(p => p.kind === 'HOST')
  return <div className="studio-page"><div className="studio-top"><div className="studio-title"><div className="studio-kicker"><span className="section-kicker">ROUND TABLE STUDIO</span><StateBadge state={d.state} /></div><h1 title={d.topic}>{d.topic}</h1>{[...d.topic].length > 55 && <button className="topic-expand" onClick={() => setShowTopic(true)}>展开完整话题</button>}</div><div className="studio-actions"><span className={`connection connection-${connection}`}>{connection === 'live' ? (d.state === 'COMPLETED' ? '内容已保存' : isMockMode ? '模拟连接正常' : '实时连接正常') : connection === 'connecting' ? '连接中…' : '连接已中断'}</span><select aria-label="切换讨论" value={id} onChange={e => navigate(`/discussion/${e.target.value}`)}>{[d, ...items.filter(item => item.id !== id)].map(item => <option key={item.id} value={item.id}>{item.topic}</option>)}</select>{snapshot.summary && <button className="secondary" onClick={() => setShowSummary(true)}>查看主持人总结</button>}</div></div>
    {connection === 'offline' && <div className="alert warning" role="alert"><span>连接中断，当前内容已保留。正在自动恢复；重新连接将读取快照并补齐发言。</span><button disabled={busy} onClick={reconnect}>重新连接</button></div>}
    {['FAILED', 'INTERRUPTED'].includes(d.state) && d.failure_stage === 'summary' && <div className="alert error" role="alert"><span>总结生成失败或中断（{d.failure_code}），正式发言和共识分歧已保留。</span><button disabled={busy} onClick={() => void act(() => discussionClient.retrySummary(id, crypto.randomUUID()))}>重试主持人总结</button></div>}
    {d.state === 'INTERRUPTED' && <div className="alert warning">讨论已中断，已发生的内容仍可查看。返回列表可创建新讨论。</div>}
    {d.state === 'FAILED' && d.failure_stage === 'discussion' && <div className="alert error" role="alert">讨论任务失败（{d.failure_code}），已提交内容保留；可返回首页新建讨论。</div>}
    {d.state === 'SUMMARIZING' && <div className="alert neutral" role="status">{snapshot.insight_status.state === 'PENDING' ? '正在核对最终发言边界的观点，随后由主持人总结…' : '主持人正在整理自然语言总结…'}</div>}
    {actionError && <div className="alert error" role="alert">{actionError}</div>}
    <div className="mobile-tabs" role="tablist" aria-label="演播厅分区">{[['guests', '嘉宾'], ['transcript', '现场发言'], ['insights', '观点与总结']].map(([key, label]) => <button role="tab" aria-selected={mobileTab === key} key={key} onClick={() => setMobileTab(key)}>{label}</button>)}</div>
    <div className="studio-grid"><section className={`panel guests-panel ${mobileTab === 'guests' ? 'mobile-visible' : ''}`} aria-label="嘉宾状态区域"><div className="panel-heading"><div><span className="section-kicker">VOICES AT THE TABLE</span><h2>圆桌嘉宾</h2></div><span className="count-badge">{d.expert_count + 1} 位</span></div><div className="guests-scroll">{host && <PersonCard person={host} status={snapshot.role_states.find(s => s.participant_id === host.id)} />}{snapshot.participants.filter(p => p.kind === 'EXPERT').map(p => <PersonCard person={p} status={snapshot.role_states.find(s => s.participant_id === p.id)} key={p.id} />)}<p className="privacy-note">仅展示角色状态与公开关注点</p></div></section>
      <Transcript snapshot={snapshot} focusId={focusId} visible={mobileTab === 'transcript'} />
      <Insights snapshot={snapshot} visible={mobileTab === 'insights'} onSource={source => { setMobileTab('transcript'); setFocusId(undefined); requestAnimationFrame(() => setFocusId(source)) }} />
    </div>{showTopic && <TopicDialog topic={d.topic} close={() => setShowTopic(false)} />}{showSummary && <SummaryDialog snapshot={snapshot} close={() => setShowSummary(false)} />}
  </div>
}
