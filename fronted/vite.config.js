import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    // shadcn-style "@/..." imports resolve to src/ (used by the landing surface).
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
    // Force a single React instance — framer-motion (landing) otherwise pulls a
    // second optimized copy in dev, breaking its hooks ("Invalid hook call").
    dedupe: ['react', 'react-dom'],
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8012',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})