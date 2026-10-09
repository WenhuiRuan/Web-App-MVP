import { HttpDiscussionClient } from './http'
import type { DiscussionClient } from './types'

// The prerecorded frontend module is loaded only in explicit independent demo mode.
export const isMockMode = new URLSearchParams(location.search).get('mode') === 'mock'
const mock = isMockMode ? await import('../mocks/client') : undefined
export const mockControls = mock?.mockControls
export const discussionClient: DiscussionClient = mock?.discussionClient ?? new HttpDiscussionClient()
export const modeDescription = isMockMode ? '前端预设演示 · 浏览器内保存 · 未调用真实模型' : '真实 HTTP/SSE · 后端持久化 · 模型模式见顶部'
