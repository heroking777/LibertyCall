# LibertyCall 管理画面 クイックスタート

## サーバー情報

- **VPS IPアドレス**: 160.251.170.253
- **フロントエンド**: http://160.251.170.253:5173
- **バックエンドAPI**: http://160.251.170.253:8000

## 起動手順

### 1. バックエンドの起動

```bash
cd /opt/libertycall
uvicorn console_backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. フロントエンドの起動（別ターミナル）

```bash
cd /opt/libertycall/frontend
npm install  # 初回のみ
npm run dev
```

### または、起動スクリプトを使用

```bash
cd /opt/libertycall
./START_SERVERS.sh
```

## アクセス

ブラウザで以下のURLにアクセス：

- **管理画面**: http://160.251.170.253:5173
- **API**: http://160.251.170.253:8000/api/logs?client_id=000&date=2025-12-05

## トラブルシューティング

### CORSエラーが発生する場合

バックエンドのCORS設定を確認してください。デフォルトでは全オリジンを許可しています。

### ポートが既に使用されている場合

```bash
# ポート8000を使用しているプロセスを確認
sudo lsof -i :8000

# ポート5173を使用しているプロセスを確認
sudo lsof -i :5173
```

### フロントエンドがバックエンドに接続できない場合

1. バックエンドが起動しているか確認
2. ファイアウォール設定を確認（ポート8000と5173が開放されているか）
3. `frontend/.env` ファイルで `VITE_API_TARGET` を確認
