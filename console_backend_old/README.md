# LibertyCall Console Backend

## セットアップ

```bash
# 依存関係のインストール
pip install -r requirements.txt
```

## 起動方法

```bash
# 開発モードで起動（リロード有効）
uvicorn console_backend.main:app --reload --host 0.0.0.0 --port 8000
```

APIは以下のURLでアクセス可能です：

- **バックエンドAPI**: `http://160.251.170.253:8000`
- **ヘルスチェック**: `http://160.251.170.253:8000/health`

## APIエンドポイント

- `GET /` - ルートエンドポイント
- `GET /health` - ヘルスチェック
- `GET /api/logs?client_id={client_id}&date={YYYY-MM-DD}` - 通話ログ一覧取得
- `GET /api/logs/{client_id}/{call_id}` - 通話ログ詳細取得

## CORS設定

デフォルトで全オリジンを許可しています（`cors_allow_origins: ["*"]`）。
本番環境では適切に制限してください。

## 環境変数

`.env` ファイルで設定可能：

- `DATABASE_URL` - データベース接続URL（デフォルト: `sqlite:///call_console.db`）
- `CORS_ALLOW_ORIGINS` - CORS許可オリジン（カンマ区切り）
- `AUTH_ENABLED` - 認証有効化（デフォルト: `False`）

