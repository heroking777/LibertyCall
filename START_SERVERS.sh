#!/bin/bash
# LibertyCall サーバー起動スクリプト

echo "=== LibertyCall サーバー起動スクリプト ==="
echo ""
echo "このスクリプトは2つのサーバーを起動します："
echo "1. FastAPI バックエンド (ポート 8000)"
echo "2. Vite フロントエンド (ポート 5173)"
echo ""
echo "Ctrl+C で両方のサーバーを停止します"
echo ""

# バックエンドをバックグラウンドで起動
echo "バックエンドを起動中..."
cd /opt/libertycall
uvicorn console_backend.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# フロントエンドをバックグラウンドで起動
echo "フロントエンドを起動中..."
cd /opt/libertycall/frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "=== サーバー起動完了 ==="
echo "バックエンド: http://0.0.0.0:8000 (PID: $BACKEND_PID)"
echo "フロントエンド: http://0.0.0.0:5173 (PID: $FRONTEND_PID)"
echo ""
echo "停止するには Ctrl+C を押してください"

# シグナルハンドラ
trap "echo 'サーバーを停止中...'; kill $BACKEND_PID $FRONTEND_PID; exit" INT TERM

# 待機
wait
