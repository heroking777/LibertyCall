# LibertyCall 管理画面フロントエンド

## セットアップ

```bash
cd frontend
npm install
```

## 環境変数設定（オプション）

`frontend/.env` ファイルを作成して、バックエンドAPIのURLを設定できます：

```bash
# バックエンドAPIのURL（本番環境用）
VITE_API_BASE_URL=http://160.251.170.253:8000

# 開発環境でのプロキシターゲット
VITE_API_TARGET=http://160.251.170.253:8000
```

デフォルトでは `http://160.251.170.253:8000` が使用されます。

## 開発サーバー起動

```bash
npm run dev
```

開発サーバーは `http://0.0.0.0:5173` で起動し、外部から以下のURLでアクセス可能です：

- **フロントエンド**: `http://160.251.170.253:5173`
- **バックエンドAPI**: `http://160.251.170.253:8000`

**注意**: バックエンド（FastAPI）も別プロセスで起動しておく必要があります：

```bash
# 別ターミナルで実行
cd /opt/libertycall
uvicorn console_backend.main:app --reload --host 0.0.0.0 --port 8000
```

## ビルド

```bash
npm run build
```

ビルド成果物は `build/` ディレクトリに出力されます。

## 機能

- **通話ログ一覧** (`/console/file-logs`)
  - クライアントIDと日付でフィルタリング
  - 通話開始時間、発信者番号、要約を表示
  - 詳細ボタンで詳細ページに遷移

- **通話ログ詳細** (`/console/file-logs/:clientId/:callId`)
  - チャットUI風のタイムライン表示
  - USERとAIの発話を色分け
  - テンプレートIDを表示

## 技術スタック

- React 18
- React Router 6
- Vite
- Axios

