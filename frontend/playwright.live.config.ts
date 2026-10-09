import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
export default defineConfig({
  testDir: './tests', testMatch: 'live*.spec.ts', workers: 1, retries: 0, timeout: 45000,
  outputDir: '../work/stage5-e2e-results',
  reporter: [['list'], ['json', { outputFile: '../work/stage5-e2e-report.json' }]],
  use: { baseURL: 'http://127.0.0.1:15174', channel: process.env.PLAYWRIGHT_CHANNEL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: [
    { command: `"${python}" -m backend.tests.e2e_server`, cwd: root, url: 'http://127.0.0.1:18081/api/health/ready', reuseExistingServer: false, env: { PYTHONUTF8: '1' } },
    { command: 'npm exec vite -- --host 127.0.0.1 --port 15174 --strictPort', url: 'http://127.0.0.1:15174', reuseExistingServer: false,
      env: { PANEL_BACKEND_ORIGIN: 'http://127.0.0.1:18081' } },
  ],
})
