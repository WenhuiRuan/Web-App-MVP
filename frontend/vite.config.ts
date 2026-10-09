import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Only a process-provided local proxy target is read; the backend .env is never loaded.
const target = process.env.PANEL_BACKEND_ORIGIN || 'http://127.0.0.1:8000'
const proxy = { '/api': { target, changeOrigin: false } }
export default defineConfig({ plugins: [react()], envPrefix: 'PANEL_PUBLIC_', server: { proxy }, preview: { proxy } })
