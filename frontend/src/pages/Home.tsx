import type { Discussion } from '../transport/types'
import { Empty, Icon, StateBadge } from '../components/shared'

export function Home({ items, status, navigate, retry, restore }: { items: Discussion[]; status: string; navigate: (path: string) => void; retry: () => void; restore: () => void }) {
  const active = items.filter(d => ['RUNNING', 'SUMMARIZING'].includes(d.state))
  const recent = items.filter(d => !['RUNNING', 'SUMMARIZING'].includes(d.state))
  return <div className="scroll-page home-page">
    <section className="home-hero"><div><p className="eyebrow">一个话题，多种视角</p><h1>把一个问题，<br />放到不同视角之间。</h1><p className="intro">让主持人串联，让专家回应。看观点如何交锋，也看共识如何慢慢形成。</p><button className="primary" onClick={() => navigate('/new')}><Icon name="plus" />新建讨论</button></div><div className="hero-art" aria-hidden="true"><div className="orbit"><span>研究</span><span>经营</span><span>经济</span><span>实践</span><b>不同观点<br />同一张圆桌</b></div><p>LISTEN · QUESTION · CONNECT</p></div></section>
    <div className="mode-note"><Icon name="spark" /><p>当前为前端模拟模式：播放预设“四天工作制”讨论。新话题用于流程体验，内容不会由模型重新分析。</p></div>
    <div className="section-title"><div><span className="section-kicker">ON AIR</span><h2>正在进行的圆桌</h2></div><span>{active.length} 场讨论</span></div>
    {status === 'loading' ? <div className="discussion-grid" role="status" aria-label="正在加载讨论列表"><div className="skeleton card-skeleton" /><div className="skeleton card-skeleton" /></div> : status === 'failed' ? <Empty title="讨论列表加载失败"><p>模拟列表暂时无法加载，请重试。</p><button className="secondary" onClick={retry}>重新加载列表</button></Empty> : !active.length ? <Empty title="暂时没有进行中的讨论"><p>开启一个话题，或载入预设圆桌体验演播厅。</p><button className="primary" onClick={() => navigate('/new')}>新建讨论</button><button className="secondary" onClick={restore}>载入示例圆桌</button></Empty> : <div className="discussion-grid">{active.map((d, i) => <article className="discussion-card" key={d.id}><div className="card-top"><StateBadge state={d.state} /><span>圆桌 {String(i + 1).padStart(2, '0')}</span></div><h3>{d.topic}</h3><p>1 位主持人 · {d.expert_count} 位专家</p><div className="card-bottom"><div className="seat-stack" aria-hidden="true"><i>文</i><i>顾</i><i>林</i><i>沈</i><i>许</i></div><button className="text-button" onClick={() => navigate(`/discussion/${d.id}`)}>进入圆桌 <Icon name="arrow" /></button></div></article>)}</div>}
    {!!recent.length && <section className="recent-section"><div className="section-title"><div><span className="section-kicker">YOUR WORKSPACE</span><h2>已保存的讨论</h2></div></div>{recent.map(d => <button className="recent-row" key={d.id} onClick={() => navigate(`/discussion/${d.id}`)}><span>{d.topic}</span><StateBadge state={d.state} /><Icon name="arrow" /></button>)}</section>}
    <div className="journey"><span><b>01</b> 提出一个问题</span><span><b>02</b> 确认嘉宾阵容</span><span><b>03</b> 观看观点交锋</span></div>
  </div>
}
