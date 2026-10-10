import { defineConfig } from '@playwright/test'
import base from './playwright.real.config'

export default defineConfig({ ...base, testMatch: 'real-quality.spec.ts',
  outputDir: '../work/stage6a-corrected-browser-results',
  reporter: [['list'], ['json', { outputFile: '../work/stage6a-corrected-browser-report.json' }]],
})
