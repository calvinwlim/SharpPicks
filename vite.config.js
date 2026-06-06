import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Forward /api/* to Vercel dev server during local development.
    // Run `vercel dev` (port 3000) alongside `npm run dev` to enable
    // the UFCStats proxy. The proxy returns null gracefully if unavailable.
    proxy: {
      '/api': {
        target:       'http://localhost:3000',
        changeOrigin: true,
      },
    },
  },
})
