import { defineConfig } from '@playwright/test'

// Explicit opt-in: this configuration contacts a paid, independently configured backend.
// Start scripts.real_validation_server separately; no provider secret enters this process.
export default defineConfig({
  testDir: './tests', testMatch: 'real-model.spec.ts', workers: 1, retries: 0, timeout: 480000,
  outputDir: '../work/stage6a-browser-results',
  reporter: [['list'], ['json', { outputFile: '../work/stage6a-browser-report.json' }]],
  use: { baseURL: 'http://127.0.0.1:15175', channel: process.env.PLAYWRIGHT_CHANNEL, viewport: { width: 1366, height: 768 }, screenshot: 'only-on-failure' },
  webServer: { command: 'npm exec vite -- --host 127.0.0.1 --port 15175 --strictPort', url: 'http://127.0.0.1:15175', reuseExistingServer: false,
    env: { PANEL_BACKEND_ORIGIN: 'http://127.0.0.1:18082' } },
})
