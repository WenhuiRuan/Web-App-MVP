import { useRef, useState } from 'react'
import { discussionClient, isMockMode } from '../transport/client'
import { Icon } from '../components/shared'

export function Create({ navigate }: { navigate: (path: string) => void }) {
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(4)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const command = useRef({ signature: '', key: crypto.randomUUID() })
  const length = [...topic.trim()].length
  const submit = async () => {
    setBusy(true); setError(undefined)
    try {
      const input = { topic: topic.trim(), expert_count: count }
      const signature = JSON.stringify(input)
      if (signature !== command.current.signature) command.current = { signature, key: crypto.randomUUID() }
      const snapshot = await discussionClient.create(input, command.current.key)
      // A generation admission failure must keep the created discussion accessible.
      try { await discussionClient.generate(snapshot.discussion.id, crypto.randomUUID()) } catch { /* Room shows DRAFT and offers retry. */ }
      navigate(`/discussion/${snapshot.discussion.id}`)
    } catch (e) { setError(e instanceof Error ? e.message : '创建失败，请重试。'); setBusy(false) }
  }
  return <div className="scroll-page create-page"><button className="back-button" onClick={() => navigate('/')}><Icon name="back" />返回讨论列表</button><div className="create-grid"><section className="create-form"><span className="section-kicker">SET THE TABLE</span><h1>今天，想讨论什么？</h1><p className="intro">从一个具体问题开始，邀请不同立场的专家加入。</p><form onSubmit={e => { e.preventDefault(); void submit() }}><label htmlFor="topic">讨论话题 <span>必填</span></label><textarea id="topic" value={topic} onChange={e => setTopic(e.target.value)} disabled={busy} maxLength={1000} placeholder="例如：四天工作制是否值得试点？" aria-describedby="topic-help" /><div className="field-help" id="topic-help"><span>1–500 字，尽量写清你想探讨的矛盾或选择。</span><span className={length > 500 ? 'error-text' : ''}>{length} / 500</span></div><label htmlFor="expert-count">专家人数</label><select id="expert-count" value={count} onChange={e => setCount(Number(e.target.value))} disabled={busy}>{[2, 3, 4, 5, 6].map(n => <option value={n} key={n}>{n} 名专家{n === 4 ? ' · 推荐' : ''}</option>)}</select><p className="field-help">主持人另计，负责开场、追问、串联与总结。</p>{error && <div className="alert error" role="alert">{error}</div>}<button className="primary wide" disabled={busy || length < 1 || length > 500} type="submit"><Icon name="spark" />{busy ? '正在准备嘉宾阵容…' : '生成嘉宾阵容'}</button></form><p className="form-note">先查看阵容，确认后才开始讨论。</p></section><aside className="create-aside"><div className="orbit small-orbit" aria-hidden="true"><span>主持</span><span>补充</span><span>反驳</span><span>追问</span><b>从观点<br />走向洞察</b></div><h2>不止听到一种声音</h2><ul><li>每位嘉宾有姓名、职业与明确立场</li><li>专家回应彼此，讨论由主持人串联</li><li>共识与分歧都有现场发言依据</li></ul><div className="mode-note"><p>{isMockMode ? '模拟阵容与发言均为预设内容，人数可调整。' : '后端按话题生成阵容并独立推进讨论。模型模式见顶部；真实服务按公开上下文生成，确定性模拟仅用于工程验证。'}</p></div></aside></div></div>
}
