import { defineConfig } from '@playwright/test'
import base from './playwright.corrected.config'

process.env.PANEL_REAL_OUTPUT ||= '../work/stage6a-final'
process.env.PANEL_REAL_TOPIC = '社区图书馆是否应试点延长晚间自助借还时段？请比较阅读可及性、老年读者使用、遗失风险与志愿者负担，并区分共同建议、个人提案和已验证事实。'
export default defineConfig({ ...base,
  timeout: 900000,
  outputDir: `${process.env.PANEL_REAL_OUTPUT}-browser-results`,
  reporter: [['list'], ['json', { outputFile: `${process.env.PANEL_REAL_OUTPUT}-browser-report.json` }]],
})
