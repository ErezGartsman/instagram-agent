import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Separate from vite.config.js (E2, SYSTEM_ELEVATION_PRD.md §A8 — first
// frontend tests): keeps the dev-server proxy/port config out of the test
// runner and vice versa. Mirrors the '@' alias so component imports resolve
// identically under test.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    dedupe: ['react', 'react-dom'],
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    globals: false,
  },
})
