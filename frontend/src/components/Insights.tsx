import { useEffect, useState } from 'react'
import type { Snapshot } from '../transport/types'
import { Empty, Icon } from './shared'

export function SummaryText({ snapshot }: { snapshot: Snapshot }) {
  return <div className="summary-text"><div className="summary-author"><span className="summary-mark"><Icon name="spark" size={22} /></span><div><strong>{snapshot.participants.find(p => p.kind === 'HOST')?.name} · 主持人总结</strong><p>基于本场 {snapshot.summary?.through_turn ?? 0} 条正式发言</p></div></div>
    {snapshot.summary?.content.split('\n\n').map((paragraph, index) => <p key={index}>{paragraph}</p>)}
    <div className="summary-note">这是预设模拟讨论的总结，不代表真实模型分析或事实验证。</div>
  </div>
}

export function Insights({ snapshot, visible, onSource }: { snapshot: Snapshot; visible: boolean; onSource: (id: string) => void }) {
  const [tab, setTab] = useState<'insights' | 'summary'>('insights')
  useEffect(() => { if (snapshot.discussion.state === 'COMPLETED') setTab('summary') }, [snapshot.discussion.state])
  const categories = [{ kind: 'consensus', label: '逐步形成的共识', symbol: '↗' }, { kind: 'disagreement', label: '仍在交锋的分歧', symbol: '↔' }] as const
  return <section className={`panel insights-panel ${visible ? 'mobile-visible' : ''}`} aria-label="共识分歧与总结区域">
    <div className="panel-heading"><div><span className="section-kicker">IDEAS IN MOTION</span><h2>观点与结论</h2></div><span className="live-small">{snapshot.discussion.state === 'COMPLETED' ? '已归档' : '随讨论更新'}</span></div>
    <div className="insight-tabs" role="tablist" aria-label="观点面板"><button role="tab" aria-selected={tab === 'insights'} onClick={() => setTab('insights')}>共识与分歧</button><button role="tab" aria-selected={tab === 'summary'} disabled={!snapshot.summary} onClick={() => setTab('summary')}>主持总结</button></div>
    <div className="insights-scroll" tabIndex={0}>
      {tab === 'summary' && snapshot.summary ? <SummaryText snapshot={snapshot} /> : <>
        <p className="insight-note">观点来自已发生的发言。点击依据，可回到讨论现场。</p>
        {categories.map(category => <div className={`insight-section ${category.kind}`} key={category.kind}>
          <h3><span>{category.symbol}</span>{category.label}<b>{snapshot.insights.items.filter(i => i.kind === category.kind).length.toString().padStart(2, '0')}</b></h3>
          {!snapshot.insights.items.some(i => i.kind === category.kind) && <div className="insight-empty">{category.kind === 'consensus' ? '观点仍在碰撞，暂未形成足够依据的共识。' : '等待不同观点的回应，分歧会在讨论中显现。'}</div>}
          {snapshot.insights.items.filter(i => i.kind === category.kind).map(insight => <article className="insight-item" data-testid="insight" key={insight.id}><p>{insight.content}</p><div className="sources"><span>发言依据</span>{insight.source_message_ids.map(id => {
            const message = snapshot.messages.find(m => m.id === id)
            if (!message) return null
            const person = snapshot.participants.find(p => p.id === message.participant_id)!
            return <button key={id} onClick={() => onSource(id)} aria-label={`查看依据 第${message.turn_no}条 ${person.name}`}><i style={{ background: person.color }} />#{message.turn_no.toString().padStart(2, '0')} {person.name}</button>
          })}</div></article>)}
        </div>)}
        {!snapshot.insights.items.length && <div className="insight-wait"><Icon name="spark" /><span>不会凭主持人开场就生成共识</span></div>}
      </>}
    </div>
    <div className="panel-footer">{snapshot.insights.version ? `已提炼至第 ${snapshot.insights.through_turn} 条发言 · 版本 ${snapshot.insights.version}` : '等待足够的发言依据'}</div>
  </section>
}
