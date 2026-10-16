import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'

// The phone's own screen (src/telefono), built to travel inside the Android app. The app shows
// it from its own files, with no server, so every path in it is relative.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist-telefono',
    emptyOutDir: true,
    rollupOptions: { input: resolve(import.meta.dirname, 'telefono.html') },
  },
})
