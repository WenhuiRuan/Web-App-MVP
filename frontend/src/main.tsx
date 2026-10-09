import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { mockControls } from './mocks/client'
import { useDiscussionList } from './hooks/useDiscussionList'
import { Icon } from './components/shared'
import { Foundation } from './components/Foundation'
import { Home } from './pages/Home'
import { Create } from './pages/Create'
import { Room } from './pages/Room'
import './style.css'

const currentPath = () => location.hash.slice(1) || '/'
function App() {
  const [path, setPath] = useState(currentPath)
  const [refresh, setRefresh] = useState(0)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [paused, setPaused] = useState(mockControls.paused)
  const [fast, setFast] = useState(mockControls.fast)
  const [notice, setNotice] = useState('')
  const { items, status } = useDiscussionList(refresh)
  const selected = path.startsWith('/discussion/') ? path.split('/')[2] : undefined
  useEffect(() => {
    const change = () => { setPath(currentPath()); setToolsOpen(false); setRefresh(n => n + 1) }
    addEventListener('hashchange', change)
    return () => removeEventListener('hashchange', change)
  }, [])
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 4000); return () => clearTimeout(timer) }, [notice])
  const navigate = (value: string) => { location.hash = value }
  const control = (action: () => void, message = '') => { action(); setToolsOpen(false); setNotice(message) }
  const restore = () => { mockControls.reset(); navigate('/'); setRefresh(n => n + 1) }
  return <div className="app-shell"><header className="app-header"><button className="brand" onClick={() => navigate('/')} aria-label="AI Panel Studio 首页"><span className="brand-mark"><i /><i /><i /></span><span>AI Panel <b>Studio</b></span></button><nav aria-label="主导航"><button aria-label="讨论列表" className={`nav-button ${path === '/' ? 'active' : ''}`} onClick={() => navigate('/')}><Icon name="grid" /><span>讨论列表</span></button><button aria-label="新建讨论" className={`nav-button ${path === '/new' ? 'active' : ''}`} onClick={() => navigate('/new')}><Icon name="plus" /><span>新建讨论</span></button></nav><div className="header-right"><span className="mock-badge">模拟模式</span><div className="tools-wrap"><button className="tools-button" aria-expanded={toolsOpen} onClick={() => setToolsOpen(!toolsOpen)}>演示工具 <span>⌄</span></button>{toolsOpen && <div className="tools-menu"><p>仅影响预设前端演示</p><button onClick={() => control(() => { mockControls.setPaused(!paused); setPaused(!paused) })}>{paused ? '继续模拟播放' : '暂停模拟播放'}</button><button onClick={() => control(() => { mockControls.fast = !fast; setFast(!fast) })}>{fast ? '切换正常演示速度' : '加快模拟播放'}</button><button onClick={() => control(() => mockControls.nextRosterFailure(), '下一次生成阵容将演示失败与重试。')}>下次生成阵容失败</button><button onClick={() => control(() => mockControls.nextSummaryFailure(), '下一场新讨论将演示总结失败与重试。')}>下次主持总结失败</button><button disabled={!selected} onClick={() => control(() => mockControls.disconnect(selected!))}>模拟当前连接中断</button><button onClick={() => control(() => { mockControls.nextListFailure(); navigate('/'); setRefresh(n => n + 1) })}>模拟列表加载失败</button><button onClick={() => control(() => { mockControls.reset(true); navigate('/'); setRefresh(n => n + 1) })}>清空模拟记录，查看空列表</button><button onClick={() => control(restore)}>恢复两场示例圆桌</button><a href="/?view=system">检查前后端基础连接 ↗</a></div>}</div></div></header>
    {paused && <div className="playback-notice">预设模拟播放已暂停 · 讨论状态未改变<button onClick={() => { mockControls.setPaused(false); setPaused(false) }}>继续播放 →</button></div>}
    <main className="app-main">{path === '/new' ? <Create navigate={navigate} /> : selected ? <Room key={selected} id={selected} items={items} navigate={navigate} /> : <Home items={items} status={status} navigate={navigate} retry={() => setRefresh(n => n + 1)} restore={restore} />}</main>
    <footer className="app-footer"><span><i />本地模拟工作空间</span><span>{mockControls.storageAvailable ? '预设事件 · 浏览器内保存 · 未调用真实模型' : '浏览器存储不可用 · 内容仅保留在当前页面'}</span></footer>{notice && <div className="toast" role="status">{notice}</div>}
  </div>
}
createRoot(document.getElementById('root')!).render(<StrictMode>{new URLSearchParams(location.search).get('view') === 'system' ? <Foundation /> : <App />}</StrictMode>)
