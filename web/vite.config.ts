import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Docker on Windows/macOS: bind mounts emit no file events, so poll (set by compose.yaml).
  server: process.env.VITE_USE_POLLING === 'true' ? { watch: { usePolling: true, interval: 300 } } : {},
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    restoreMocks: true,
  },
})
