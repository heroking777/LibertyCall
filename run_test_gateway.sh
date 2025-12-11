#!/bin/bash
# ASRエラーテスト用Gateway起動スクリプト
# 無効な認証パスを設定してASRエラーを意図的に発生させる

set -e

echo "=== ASRエラーテスト用Gateway起動 ==="
echo ""

# venvを有効化
source /opt/libertycall/venv/bin/activate

# 無効な認証パスを設定（ASRエラーを意図的に発生させる）
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/invalid_dummy.json"
export LC_GOOGLE_CREDENTIALS_PATH="/opt/libertycall/key/invalid_dummy.json"
export LC_GOOGLE_PROJECT_ID="libertycall-main"

echo "環境変数を設定しました:"
echo "  GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
echo "  LC_GOOGLE_CREDENTIALS_PATH=${LC_GOOGLE_CREDENTIALS_PATH}"
echo "  LC_GOOGLE_PROJECT_ID=${LC_GOOGLE_PROJECT_ID}"
echo ""

# ログファイルのパス（標準出力をリダイレクト）
LOG_DIR="/opt/libertycall/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/realtime_gateway.log"

echo "ログファイル: ${LOG_FILE}"
echo ""

# 別ポートで起動（本番環境と競合しないように）
if [ -z "$LC_RTP_PORT" ] && [ -z "$LC_GATEWAY_PORT" ]; then
    export LC_RTP_PORT=7001
    echo "テスト用ポート: ${LC_RTP_PORT} (本番は7000)"
    echo ""
fi

echo "Gatewayを起動します..."
echo "（Ctrl+Cで終了）"
echo ""

# gatewayを起動（標準出力と標準エラーをログファイルにリダイレクト）
cd /opt/libertycall
python gateway/realtime_gateway.py 2>&1 | tee "$LOG_FILE"

