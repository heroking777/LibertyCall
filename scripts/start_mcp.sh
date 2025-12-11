#!/bin/bash
# -----------------------------------------------------------------------------
# 開発・手動起動用スクリプトです。本番/常駐運用は systemd
#   (libertycall-mcp.service / libertycall-ngrok.service) を必ず利用してください。
# ngrok 公開URLをすぐ確認したい場合のみ、このスクリプトで手動起動します。
# 常駐化コマンド例:
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now libertycall-mcp.service
#   sudo systemctl enable --now libertycall-ngrok.service
#   sudo systemctl status libertycall-mcp.service
#   sudo systemctl status libertycall-ngrok.service
# -----------------------------------------------------------------------------
set -euo pipefail

BASE="/opt/libertycall"
LOG_DIR="$BASE/logs"
VENV="$BASE/venv/bin/activate"
NGROK_API="http://127.0.0.1:4040/api/tunnels"
MCP_PORT="${MCP_PORT:-8000}"
MCP_PATH="${MCP_PATH:-/mcp}"

mkdir -p "$LOG_DIR"

echo "[INFO] Activating venv..."
if [[ ! -f "$VENV" ]]; then
  echo "[ERROR] venv が見つかりません: $VENV" >&2
  exit 1
fi
source "$VENV"

echo "[INFO] Starting MCP server..."
nohup python3 -m libertycall_mcp_http.server \
  --host 0.0.0.0 \
  --port "$MCP_PORT" \
  --path "$MCP_PATH" \
  > "$LOG_DIR/mcp_server.log" 2>&1 &
MCP_PID=$!

echo "[INFO] Starting ngrok tunnel..."
nohup ngrok http "$MCP_PORT" \
  > "$LOG_DIR/ngrok.log" 2>&1 &
NGROK_PID=$!

sleep 3

echo "[INFO] Fetching ngrok public URL..."
PUBLIC_URL="$(curl -s "$NGROK_API" | grep -oE 'https://[a-zA-Z0-9.-]+\.ngrok-free\.dev' | head -n 1 || true)"

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[ERROR] Could not retrieve ngrok public URL."
  echo "[INFO] Check $LOG_DIR/ngrok.log for details."
  exit 1
fi

echo "[INFO] MCP endpoint available at:"
echo "${PUBLIC_URL}${MCP_PATH}"
echo "[INFO] MCP PID: $MCP_PID"
echo "[INFO] ngrok PID: $NGROK_PID"

