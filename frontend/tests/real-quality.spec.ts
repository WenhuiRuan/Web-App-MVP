import { test, expect } from '@playwright/test'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import type { Snapshot } from '../src/transport/types'

test.skip(!process.env.PANEL_REAL_VALIDATION, 'Explicit opt-in for paid real model validation')
test('corrected real model flows from creation through live evidence to final summary', async ({ page }) => {
  const output = process.env.PANEL_REAL_OUTPUT || '../work/stage6a-corrected'
  if (existsSync(`${output}/discussion.json`)) throw new Error('Retain prior evidence; do not overwrite a completed run')
  mkdirSync(output, { recursive: true })
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message))
  const topic = process.env.PANEL_REAL_TOPIC || '社区图书馆是否应试点周日自助借还服务？请比较阅读可及性、图书遗失风险、设备成本与志愿者负担，并区分个人建议与共同认可的条件。'
  const started = Date.now()
  await page.goto('/#/new')
  await expect(page.locator('.mock-badge')).toHaveText('DeepSeek · deepseek-flash（真实服务）')
  await page.getByLabel('讨论话题').fill(topic)
  await page.getByRole('button', { name: '生成嘉宾阵容', exact: true }).click()
  await expect(page.getByRole('status', { name: '嘉宾阵容生成中' })).toBeVisible()
  await expect(page.getByTestId('roster-person')).toHaveCount(5, { timeout: 100000 })
  await page.screenshot({ path: `${output}/roster.png` })
  const id = page.url().split('/discussion/')[1]
  await page.getByRole('button', { name: '确认阵容，进入演播厅' }).click()
  await expect(page.getByRole('heading', { name: '现场 Transcript' })).toBeVisible()
  const observations: unknown[] = []; const versions: unknown[] = []
  let snapshot: Snapshot | undefined; let version = 0; let savedWaiting = false; let savedLive = false
  for (let attempt = 0; attempt < 330; attempt++) {
    snapshot = await (await page.request.get(`/api/discussions/${id}`)).json() as Snapshot
    observations.push({ elapsed_ms: Date.now() - started, state: snapshot.discussion.state,
      messages: snapshot.messages.length, insight_status: snapshot.insight_status,
      insight_version: snapshot.insights.version, role_states: snapshot.role_states })
    if (snapshot.insights.version > version) {
      version = snapshot.insights.version
      versions.push({ state: snapshot.discussion.state, message_count: snapshot.messages.length, insights: snapshot.insights })
    }
    if (!savedWaiting && snapshot.role_states.some(s => s.state === 'SPEAKING')) {
      await page.screenshot({ path: `${output}/waiting.png` }); savedWaiting = true
    }
    if (!savedLive && snapshot.discussion.state === 'RUNNING' && snapshot.insights.items.length > 0) {
      await expect(page.getByTestId('insight').first()).toBeVisible()
      await page.screenshot({ path: `${output}/live.png` }); savedLive = true
    }
    if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(snapshot.discussion.state)) break
    await page.waitForTimeout(1000)
  }
  writeFileSync(`${output}/discussion.json`, JSON.stringify({ snapshot, observations, versions, errors,
    elapsed_ms: Date.now() - started }, null, 2))
  expect(snapshot?.discussion.state, JSON.stringify(snapshot?.discussion)).toBe('COMPLETED')
  expect(savedWaiting).toBeTruthy(); expect(savedLive).toBeTruthy()
  expect(versions.length).toBeGreaterThanOrEqual(2)
  await expect(page.getByTestId('message')).toHaveCount(snapshot!.messages.length)
  expect(await page.getByTestId('message').evaluateAll(nodes => nodes.map(n => n.getAttribute('data-message-id'))))
    .toEqual(snapshot!.messages.map(m => m.id))
  for (const insight of snapshot!.insights.items) await expect(page.getByTestId('insight').filter({ hasText: insight.content })).toBeVisible()
  await page.getByRole('button', { name: '查看主持人总结' }).click()
  await expect(page.getByRole('dialog')).toContainText(snapshot!.summary!.content.split('\n')[0])
  expect(await page.getByRole('dialog').innerText()).not.toContain('{"')
  await page.screenshot({ path: `${output}/summary.png` })
  expect(errors).toEqual([])
})
