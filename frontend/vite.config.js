import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// バックエンドAPIのURL（環境変数から取得、デフォルトは実際のIP）
// 注意: バックエンドはポート8001で起動している
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true, // ポートが使用中の場合はエラーにする（別ポートにフォールバックしない）
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
  },
})
