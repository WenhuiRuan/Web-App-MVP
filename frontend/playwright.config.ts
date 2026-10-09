import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
export default defineConfig({
  testDir: './tests', workers: 1, retries: 0,
  use: { baseURL: 'http://127.0.0.1:15173', channel: process.env.PLAYWRIGHT_CHANNEL, trace: 'retain-on-failure' },
  webServer: [
    { command: `"${python}" -m backend.app.server`, cwd: root, url: 'http://127.0.0.1:18080/api/health/ready', reuseExistingServer: false,
      env: { BACKEND_PORT: '18080', DATABASE_PATH: 'work/browser-smoke.sqlite3', MODEL_PROVIDER: 'mock', MODEL_API_KEY: 'browser-secret-sentinel' } },
    { command: 'npm exec vite -- --host 127.0.0.1 --port 15173 --strictPort', url: 'http://127.0.0.1:15173', reuseExistingServer: false,
      env: { PANEL_BACKEND_ORIGIN: 'http://127.0.0.1:18080' } }
  ],
})
