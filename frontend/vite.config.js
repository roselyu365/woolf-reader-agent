import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/reader': 'http://localhost:8001',
      '/notes':  'http://localhost:8001',
      '/mobile': 'http://localhost:8001',
    }
  }
})
