import { defineConfig } from '@playwright/test'
import base from './playwright.real.config'

// Explicit opt-in real service; no keys in the frontend environment.
export default defineConfig({ ...base, testMatch: 'real-quality.spec.ts', timeout: 1050000,
  outputDir: '../work/stage6c-browser-results',
  reporter: [['list'], ['json', { outputFile: '../work/stage6c-browser-report.json' }]],
})
