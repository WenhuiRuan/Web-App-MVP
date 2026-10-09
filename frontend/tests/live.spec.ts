import { test, expect, type Page, type APIRequestContext } from '@playwright/test'
import { mkdirSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import type { Snapshot } from '../src/transport/types'

const screenshots = path.resolve('../work/stage5-screenshots')
mkdirSync(screenshots, { recursive: true })
async function snapshot(api: APIRequestContext, id: string): Promise<Snapshot> {
  const response = await api.get(`/api/discussions/${id}`); expect(response.ok()).toBeTruthy(); return response.json()
}
async function control(api: APIRequestContext, id: string, options: Record<string, unknown>) {
  const response = await api.post(`/api/_test/control/${id}`, { data: options }); expect(response.ok()).toBeTruthy()
}
async function create(page: Page, topic: string, options: Record<string, unknown> = {}) {
  await page.goto('/#/new')
  await expect(page.getByLabel('专家人数')).toHaveValue('4')
  await page.getByLabel('讨论话题').fill(topic)
  await page.getByRole('button', { name: '生成嘉宾阵容', exact: true }).click()
  await expect(page.getByTestId('roster-person')).toHaveCount(5)
  const id = page.url().split('/discussion/')[1]
  expect(id).toMatch(/^[0-9a-f-]{36}$/)
  await control(page.request, id, options)
  return id
}
async function start(page: Page) {
  await page.getByRole('button', { name: '确认阵容，进入演播厅' }).click()
  await expect(page.getByRole('heading', { name: '现场 Transcript' })).toBeVisible()
}
async function complete(page: Page, id: string, count: number) {
  await expect(page.getByRole('button', { name: '查看主持人总结' })).toBeVisible({ timeout: 25000 })
  await expect(page.getByTestId('message')).toHaveCount(count)
  const data = await snapshot(page.request, id)
  expect(data.discussion.state).toBe('COMPLETED')
  const ids = await page.getByTestId('message').evaluateAll(nodes => nodes.map(n => n.getAttribute('data-message-id')))
  expect(ids).toEqual(data.messages.map(m => m.id))
  expect(new Set(ids).size).toBe(count)
  return data
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }))).toEqual({ width: page.viewportSize()!.width, height: page.viewportSize()!.height })
  expect(await page.locator('.panel:visible,.app-header,.scroll-page').evaluateAll(elements => elements.filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.className))).toEqual([])
}

test('real services create, confirm, stream two live evidence updates and complete a natural summary', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  const requests: string[] = []; page.on('request', r => requests.push(`${r.method()} ${new URL(r.url()).pathname}`))
  const id = await create(page, '真实链路甲：如何验证试点边界', { pause_after: 4 })
  await expect(page.getByText('后端确定性模拟', { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(screenshots, 'roster-live.png') })
  await start(page)
  await expect(page.getByTestId('message')).toHaveCount(4)
  await expect(page.getByTestId('insight')).not.toHaveCount(0)
  const first = await snapshot(page.request, id)
  expect(first.discussion.state).toBe('RUNNING'); expect(first.insights.through_turn).toBe(4)
  await control(page.request, id, { pause_after: 6 })
  await expect(page.getByTestId('message')).toHaveCount(6)
  await expect(page.locator('.insights-panel .panel-footer')).toContainText('第 6 条')
  expect((await snapshot(page.request, id)).insights.version).toBeGreaterThan(first.insights.version)
  await page.screenshot({ path: path.join(screenshots, 'studio-live.png') })
  await control(page.request, id, {})
  const data = await complete(page, id, 8)
  for (const message of data.messages) {
    const person = data.participants.find(p => p.id === message.participant_id)!
    const row = page.locator(`[data-message-id="${message.id}"]`)
    await expect(row.locator('.message-meta strong')).toHaveText(person.name)
    await expect(row.locator('.message-meta span')).toHaveText(person.title)
    expect(await row.evaluate(e => (e as HTMLElement).style.getPropertyValue('--role'))).toBe(person.color)
  }
  expect(await page.locator('.guests-panel').innerText()).not.toMatch(/chain.of.thought|隐藏推理|内部推理/)
  await expect(page.getByText('仅展示角色状态与公开关注点')).toBeVisible()
  await page.getByRole('button', { name: '查看主持人总结' }).click()
  await expect(page.getByRole('dialog')).toContainText('主要观点')
  expect(await page.getByRole('dialog').innerText()).not.toContain('{"')
  await page.screenshot({ path: path.join(screenshots, 'summary-live.png') })
  expect(requests).toContain('POST /api/discussions')
  expect(requests).toContain(`POST /api/discussions/${id}/roster-generation`)
  expect(requests).toContain(`POST /api/discussions/${id}/start`)
  expect(requests).toContain(`GET /api/discussions/${id}/events`)
  expect(await page.evaluate(() => localStorage.getItem('ai-panel-studio.frontend-demo.v1'))).toBeNull()
  expect(errors).toEqual([])
})

test('home joins an active discussion and refresh restores persisted content', async ({ page, context }) => {
  const topic = '中途加入乙：协作边界'
  const id = await create(page, topic, { pause_after: 4, stop_after: 12 })
  await start(page); await expect(page.getByTestId('message')).toHaveCount(4)
  const before = await snapshot(page.request, id)
  const visitor = await context.newPage()
  await visitor.goto('/')
  const card = visitor.locator('.discussion-card').filter({ hasText: topic })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: /进入圆桌/ }).click()
  await expect(visitor.getByTestId('message')).toHaveCount(4)
  await visitor.reload(); await expect(visitor.getByTestId('message')).toHaveCount(4)
  expect(await visitor.getByTestId('message').evaluateAll(nodes => nodes.map(n => n.getAttribute('data-message-id')))).toEqual(before.messages.map(m => m.id))
  await control(page.request, id, { stop_after: 12 })
  await complete(visitor, id, 12); await visitor.close()
})

test('actual network disconnect leaves engine running and automatically restores complete unique messages', async ({ page, context }) => {
  const id = await create(page, '断线补发丙：试点与成本', { pause_after: 4, stop_after: 12 })
  await start(page); await expect(page.getByTestId('message')).toHaveCount(4)
  const before = await snapshot(page.request, id)
  await context.setOffline(true)
  await control(page.request, id, { stop_after: 12 })
  await expect.poll(async () => (await snapshot(page.request, id)).discussion.state, { timeout: 20000 }).toBe('COMPLETED')
  await expect(page.getByTestId('message')).toHaveCount(4)
  await context.setOffline(false)
  const data = await complete(page, id, 12)
  expect(data.messages.slice(0, 4)).toEqual(before.messages)
  const stream = await page.request.get(`/api/discussions/${id}/events`, { headers: { 'Last-Event-ID': `${id}:${before.last_event_seq}` } })
  const events = (await stream.text()).split('\n').filter(l => l.startsWith('data: ')).map(l => JSON.parse(l.slice(6)))
  expect(events.map(e => e.seq)).toEqual(Array.from({ length: data.last_event_seq - before.last_event_seq }, (_, i) => before.last_event_seq + i + 1))
  expect(events.filter(e => e.type === 'turn.committed')).toHaveLength(8)
})

test('summary failure retries the same frozen run without changing messages or evidence', async ({ page }) => {
  const id = await create(page, '总结故障丁：验证恢复', { summary_fails: true })
  await start(page)
  await expect(page.getByRole('button', { name: '重试主持人总结' })).toBeVisible({ timeout: 20000 })
  const before = await snapshot(page.request, id)
  expect(before.discussion.failure_code).toBe('MODEL_RESULT_INVALID')
  expect(before.messages).toHaveLength(8)
  await page.screenshot({ path: path.join(screenshots, 'summary-failure-live.png') })
  await control(page.request, id, {})
  await page.getByRole('button', { name: '重试主持人总结' }).click()
  const after = await complete(page, id, 8)
  expect(after.messages).toEqual(before.messages); expect(after.insights).toEqual(before.insights)
  expect(after.discussion.run_id).toBe(before.discussion.run_id)
  expect(after.discussion.failure_code).toBeNull()
  const calls = await (await page.request.get(`/api/_test/calls/${id}`)).json()
  expect(calls.filter((c: { task: string }) => c.task === 'roster')).toHaveLength(1)
  expect(calls.filter((c: { task: string }) => c.task === 'utterance')).toHaveLength(8)
  expect(calls.filter((c: { task: string }) => c.task === 'summary')).toHaveLength(3)
})

for (const fault of ['gap', 'duplicate', 'disconnect']) test(`real SSE ${fault} recovers without losing or duplicating submitted messages`, async ({ page }) => {
  const id = await create(page, `事件恢复${fault}：重新读取快照`, { pause_after: 4, stop_after: 12 })
  await start(page); await expect(page.getByTestId('message')).toHaveCount(4)
  const before = await snapshot(page.request, id)
  let snapshotReads = 0
  page.on('request', r => { if (new URL(r.url()).pathname === `/api/discussions/${id}`) snapshotReads++ })
  await control(page.request, id, { stop_after: 12, stream_fault: fault })
  const data = await complete(page, id, 12)
  expect(data.messages.slice(0, 4)).toEqual(before.messages)
  if (fault !== 'duplicate') expect(snapshotReads).toBeGreaterThan(0)
})

test('failed extraction is streamed while last successful evidence stays visible', async ({ page }) => {
  const id = await create(page, '观点故障戊：保留已有证据', { pause_after: 4 })
  await start(page); await expect(page.getByTestId('message')).toHaveCount(4)
  await expect(page.getByTestId('insight')).not.toHaveCount(0)
  const before = await snapshot(page.request, id)
  await control(page.request, id, { pause_after: 6, insights_fail_from: 6 })
  await expect(page.getByTestId('insight-failure')).toBeVisible()
  await expect(page.getByTestId('insight-failure')).toContainText('已保留最近成功')
  expect((await snapshot(page.request, id)).insights).toEqual(before.insights)
  await expect(page.getByTestId('insight')).toHaveCount(before.insights.items.length)
  await page.screenshot({ path: path.join(screenshots, 'insight-failure-live.png') })
  await control(page.request, id, { insights_fail_from: 6 })
  const after = await complete(page, id, 8)
  expect(after.insights).toEqual(before.insights)
  await expect(page.getByTestId('insight-failure')).toBeVisible()
})

test('two discussions interleave and switching pages cannot leak events or evidence', async ({ page, context }) => {
  const a = await create(page, '隔离甲场：效率', { pause_after: 4 })
  await start(page); await expect(page.getByTestId('message')).toHaveCount(4)
  const second = await context.newPage()
  const b = await create(second, '隔离乙场：公平', { pause_after: 4, summary_fails: true })
  await start(second); await expect(second.getByTestId('message')).toHaveCount(4)
  await expect.poll(async () => (await snapshot(page.request, b)).insights.items.length).toBeGreaterThan(0)
  await expect.poll(() => page.getByLabel('切换讨论').locator('option').count()).toBeGreaterThanOrEqual(2)
  await page.getByLabel('切换讨论').selectOption(b)
  await expect(page.locator('.studio-title h1')).toHaveText('隔离乙场：公平')
  await expect(page.getByTestId('message')).toHaveCount(4)
  expect(await page.locator('.transcript-scroll').innerText()).not.toContain('隔离甲场')
  expect(await page.locator('.insights-scroll').innerText()).not.toContain('隔离甲场')
  await page.getByLabel('切换讨论').selectOption(a)
  await expect(page.locator('.studio-title h1')).toHaveText('隔离甲场：效率')
  await control(page.request, a, {})
  await control(page.request, b, { summary_fails: true })
  const aResult = await complete(page, a, 8)
  await expect(second.getByRole('button', { name: '重试主持人总结' })).toBeVisible({ timeout: 20000 })
  const bResult = await snapshot(page.request, b)
  expect(bResult.discussion.state).toBe('FAILED')
  expect(aResult.discussion.run_id).not.toBe(bResult.discussion.run_id)
  for (const result of [aResult, bResult]) {
    const ids = new Set(result.messages.map(m => m.id))
    expect(result.messages.every(m => m.discussion_id === result.discussion.id && m.run_id === result.discussion.run_id)).toBeTruthy()
    expect(result.insights.items.every(i => i.source_message_ids.every(id => ids.has(id)))).toBeTruthy()
  }
  await second.close()
})

for (const [width, height] of [[1366, 768], [2560, 1080], [390, 844]]) test(`real growing content ${width}x${height} keeps reading position and internal scroll`, async ({ page }) => {
  await page.setViewportSize({ width, height })
  const id = await create(page, `动态内容${width}：成本和试点条件`, { stop_after: 24, pause_after: 12, long_content: true, delay: .03 })
  await start(page); await expect(page.getByTestId('message')).toHaveCount(12)
  await noOverflow(page)
  const box = page.getByTestId('transcript-scroll')
  expect(await box.evaluate(e => e.scrollHeight > e.clientHeight)).toBeTruthy()
  await box.evaluate(e => { e.scrollTop = 0; e.dispatchEvent(new Event('scroll')) })
  await expect(page.getByTestId('message').first()).toBeInViewport()
  await control(page.request, id, { stop_after: 24, pause_after: 18, long_content: true, delay: .03 })
  await expect(page.getByTestId('message')).toHaveCount(18)
  expect(await box.evaluate(e => e.scrollTop)).toBe(0)
  await expect(page.getByRole('button', { name: /条新发言 · 回到现场/ })).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: path.join(screenshots, `growing-${width}.png`) })
  await page.getByRole('button', { name: /条新发言 · 回到现场/ }).click()
  await expect(page.getByTestId('message').last()).toBeInViewport()
  if (width === 390) {
    await page.getByRole('tab', { name: '嘉宾', exact: true }).click()
    await expect(page.getByRole('heading', { name: '圆桌嘉宾' })).toBeVisible()
    await page.locator('.guests-scroll').evaluate(e => e.scrollTop = e.scrollHeight)
    await expect(page.getByTestId('expert-card').last()).toBeInViewport()
    await noOverflow(page)
    await page.getByRole('tab', { name: '观点与总结', exact: true }).click()
    await expect(page.getByTestId('insight').first()).toBeVisible()
    await page.getByRole('button', { name: /查看依据/ }).first().click()
    await expect(page.locator('.cited-message')).toBeInViewport()
  }
  if (width === 2560) expect((await page.locator('.transcript-panel').boundingBox())!.width).toBeLessThanOrEqual(760)
  await control(page.request, id, { stop_after: 24, long_content: true, delay: .03 })
  await complete(page, id, 24)
  await noOverflow(page)
  await page.getByRole('button', { name: '查看主持人总结' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: path.join(screenshots, `summary-${width}.png`) })
})

test('browser API responses and production assets never contain the backend-only key', async ({ page }) => {
  const sentinel = 'stage5-backend-secret-sentinel'
  const id = await create(page, '密钥边界检查己')
  await start(page); await complete(page, id, 8)
  for (const url of ['/api/system', '/api/health/ready', '/api/discussions?status=all', `/api/discussions/${id}`, `/api/discussions/${id}/events?after=0`, '/api/discussions/not-a-uuid']) {
    const response = await page.request.get(url)
    expect(await response.text()).not.toContain(sentinel)
    expect(JSON.stringify(response.headers())).not.toContain(sentinel)
  }
  expect(await page.content()).not.toContain(sentinel)
  const scan = (directory: string) => {
    for (const file of readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, file.name)
      if (file.isDirectory()) scan(full)
      else expect(readFileSync(full, 'utf8')).not.toContain(sentinel)
    }
  }
  scan(path.resolve('dist'))
})
