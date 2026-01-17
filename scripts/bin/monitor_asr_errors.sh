#!/bin/bash
# ASRエラー監視用スクリプト
# リアルタイムでASRエラー関連のログを表示

# ログファイル候補（優先順位順）
LOG_CANDIDATES=(
    "/opt/libertycall/logs/realtime_gateway.log"
    "/opt/libertycall/logs/gateway.log"
    "/var/log/libertycall.log"
)

# 引数で指定された場合はそれを使用
if [ -n "$1" ]; then
    LOG_FILE="$1"
else
    # 候補から最初に見つかったファイルを使用
    LOG_FILE=""
    for candidate in "${LOG_CANDIDATES[@]}"; do
        if [ -f "$candidate" ]; then
            LOG_FILE="$candidate"
            break
        fi
    done
    
    # 見つからなかった場合は最初の候補をデフォルトとして使用（tail -fで作成される可能性がある）
    if [ -z "$LOG_FILE" ]; then
        LOG_FILE="${LOG_CANDIDATES[0]}"
        echo "警告: ログファイルが見つかりません。新規作成される可能性があります: ${LOG_FILE}"
    fi
fi

echo "=== ASRエラー監視開始 ==="
echo "監視対象ログ: ${LOG_FILE}"
echo "監視キーワード: ASR_ERROR, ASR_GOOGLE_ERROR, ASR_ERROR_HANDLER, STREAM_WORKER_CRASHED, TRANSFER"
echo ""
echo "--- ログ出力開始（Ctrl+Cで終了） ---"
echo ""

# ファイルが存在する場合はtail -f、存在しない場合は作成を待つ
if [ -f "$LOG_FILE" ]; then
    tail -f "$LOG_FILE" 2>/dev/null | grep --line-buffered -E "ASR_ERROR|ASR_GOOGLE_ERROR|ASR_ERROR_HANDLER|STREAM_WORKER_CRASHED|TRANSFER"
else
    # ファイルが存在しない場合、ディレクトリを作成してから監視開始
    LOG_DIR=$(dirname "$LOG_FILE")
    mkdir -p "$LOG_DIR" 2>/dev/null
    echo "ログファイルを待機中: ${LOG_FILE}"
    echo "（gatewayが起動すると自動的に監視を開始します）"
    echo ""
    # ファイルが作成されるまで待機
    while [ ! -f "$LOG_FILE" ]; do
        sleep 1
    done
    tail -f "$LOG_FILE" 2>/dev/null | grep --line-buffered -E "ASR_ERROR|ASR_GOOGLE_ERROR|ASR_ERROR_HANDLER|STREAM_WORKER_CRASHED|TRANSFER"
fi

