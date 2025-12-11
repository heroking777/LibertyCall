// API設定
// 開発環境・本番環境ともに同じドメインの/api/を使用（Nginxプロキシ経由）
// これにより、Basic認証を通過した状態でAPIにアクセスできる
const isDev = import.meta.env.DEV
export const API_BASE = '/api'

// デバッグ用（開発時のみ表示）
if (isDev) {
  console.log('API_BASE:', API_BASE)
  console.log('API_BASE_URL:', API_BASE_URL)
}

