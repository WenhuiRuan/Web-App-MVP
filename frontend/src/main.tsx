import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type SystemInfo = { name: string; version: string; phase: number; model_mode: 'mock' | 'unavailable'; discussion_engine_available: false }
type Connection = { status: 'loading' | 'ready' | 'failed'; info?: SystemInfo }

function App() {
  const [attempt, retry] = useState(0)
  const [connection, setConnection] = useState<Connection>({ status: 'loading' })
  useEffect(() => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 8000)
    let active = true
    setConnection({ status: 'loading' })
    Promise.all(['/api/system', '/api/health/ready'].map(async path => {
      const response = await fetch(path, { signal: controller.signal })
      if (!response.ok) throw new Error('服务尚未就绪')
      return response.json()
    })).then(([info]) => { if (active) setConnection({ status: 'ready', info: info as SystemInfo }) })
      .catch(() => { if (active) setConnection({ status: 'failed' }) })
      .finally(() => clearTimeout(timeout))
    return () => { active = false; clearTimeout(timeout); controller.abort() }
  }, [attempt])
  return <main>
    <header><span className="mark">P</span><span>AI Panel Studio</span><span className="stage">阶段 02 · 工程基础</span></header>
    <section className="workspace">
      <p className="eyebrow">让不同观点在同一张圆桌相遇</p>
      <h1>讨论，从连接开始。</h1>
      <p className="intro">前后端与数据存储正在就位。嘉宾生成、实时圆桌和讨论总结将在后续阶段开放。</p>
      <div className="status-card" aria-live="polite">
        <div className={`indicator ${connection.status}`} />
        <div><h2>{connection.status === 'ready' ? '基础服务已连接' : connection.status === 'loading' ? '正在检查连接…' : '基础服务未连接'}</h2>
          <p>{connection.status === 'ready' ? '数据库已就绪 · 确定性模拟模式' : connection.status === 'loading' ? '正在检查后端与数据库状态' : '请检查本地后端是否已启动，再重试连接。'}</p></div>
        <button onClick={() => retry(n => n + 1)} disabled={connection.status === 'loading'}>重新检查</button>
      </div>
      <div className="next"><span>下一步</span><p>完成讨论创建、阵容确认和演播厅页面设计。</p></div>
    </section>
    <footer><span>本地工作空间</span><span>当前不调用真实模型服务</span></footer>
  </main>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
