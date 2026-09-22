import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy the API so the browser sees a single origin and CORS never applies.
    proxy: {
      // Overridable so a second checkout can run its own backend alongside the
      // usual one without the two fighting over port 8000.
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
