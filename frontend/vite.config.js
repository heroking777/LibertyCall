import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'build',
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-v2-[hash].js',
        chunkFileNames: 'assets/[name]-v2-[hash].js',
        assetFileNames: 'assets/[name]-v2-[hash].[ext]',
      },
    },
  },
})
