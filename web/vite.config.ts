import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // In development the page comes from Vite and everything under /api from the running app
    proxy: { '/api': process.env.API_URL ?? 'http://127.0.0.1:8090' },
    watch: {
      // Inside a container, file change events do not arrive from Windows: look for changes instead
      usePolling: Boolean(process.env.WATCH_BY_POLLING),
      interval: 500,
    },
  },
})
