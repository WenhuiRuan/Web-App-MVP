import { test, expect } from '@playwright/test'

test('real frontend reaches real backend through proxy, with no provider secret', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/?view=system')
  await expect(page.getByRole('heading', { name: '基础服务已连接' })).toBeVisible()
  await expect(page.getByText('数据库已就绪 · 确定性模拟模式')).toBeVisible()
  const response = await page.request.get('/api/system')
  expect(response.ok()).toBeTruthy()
  expect(await response.json()).toMatchObject({ phase: 2, model_mode: 'mock', discussion_engine_available: false })
  expect(await response.text()).not.toContain('browser-secret-sentinel')
  expect(await page.content()).not.toContain('browser-secret-sentinel')
  await page.getByRole('button', { name: '重新检查' }).click()
  await expect(page.getByRole('heading', { name: '基础服务已连接' })).toBeVisible()
  expect(errors).toEqual([])
})

test('foundation status remains usable on a narrow screen and shows unavailable state', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?view=system')
  await expect(page.getByRole('heading', { name: '基础服务已连接' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.route('**/api/health/ready', route => route.fulfill({ status: 503, body: '{}' }))
  await page.getByRole('button', { name: '重新检查' }).click()
  await expect(page.getByRole('heading', { name: '基础服务未连接' })).toBeVisible()
})
