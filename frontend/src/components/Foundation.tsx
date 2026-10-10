import { useEffect, useState } from 'react'

export function Foundation() {
  const [attempt, retry] = useState(0)
  const [status, setStatus] = useState('loading')
  const [modelLabel, setModelLabel] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 8000)
    let active = true
    setStatus('loading')
    Promise.all(['/api/system', '/api/health/ready'].map(async path => {
      const response = await fetch(path, { signal: controller.signal })
      if (!response.ok) throw new Error('服务尚未就绪')
      return response.json()
    })).then(([info]) => { if (active) { setStatus('ready'); setModelLabel(info.model_mode === 'real' ? `真实服务 · ${info.model_name}` : '后端确定性模拟') } }).catch(() => { if (active) setStatus('failed') }).finally(() => clearTimeout(timer))
    return () => { active = false; clearTimeout(timer); controller.abort() }
  }, [attempt])
  return <main className="foundation"><a href="/">← 返回圆桌</a><span className="section-kicker">AI PANEL STUDIO · 基础服务检查</span><h1>讨论，从连接开始。</h1><div className="status-card" aria-live="polite"><h2>{status === 'ready' ? '基础服务已连接' : status === 'loading' ? '正在检查连接…' : '基础服务未连接'}</h2><p>{status === 'ready' ? `数据库已就绪 · ${modelLabel}` : status === 'loading' ? '正在检查后端与数据库状态' : '请检查本地后端是否已启动，再重试连接。'}</p><button className="secondary" onClick={() => retry(n => n + 1)} disabled={status === 'loading'}>重新检查</button></div><p>就绪检查仅检查配置和数据库，不发起付费模型调用。</p></main>
}
