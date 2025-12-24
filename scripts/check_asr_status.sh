#!/bin/bash
# ASR状態確認スクリプト

echo "=========================================="
echo "ASR状態確認"
echo "=========================================="
echo ""

echo "1. プロセス確認"
echo "----------------------------------------"
echo "gateway_event_listener:"
ps aux | grep gateway_event_listener | grep -v grep || echo "  ❌ 実行されていません"
echo ""
echo "realtime_gateway:"
ps aux | grep realtime_gateway | grep -v grep || echo "  ❌ 実行されていません（着信時に起動されます）"
echo ""

echo "2. 最新のログファイル確認"
echo "----------------------------------------"
LATEST_LOG=$(ls -t /tmp/gateway_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    echo "最新ログ: $LATEST_LOG"
    echo ""
    echo "ASR関連ログ:"
    grep -E "ASR_HOOK|ASR_DEBUG|ASRHandler|GoogleStreamingASR|streaming_enabled" "$LATEST_LOG" | tail -10 || echo "  ASR関連ログが見つかりません"
    echo ""
    echo "STREAMING_FEEDログ:"
    grep "STREAMING_FEED" "$LATEST_LOG" | tail -5 || echo "  STREAMING_FEEDログが見つかりません"
else
    echo "  ❌ ログファイルが見つかりません"
fi
echo ""

echo "3. 環境変数確認"
echo "----------------------------------------"
echo "LC_ASR_STREAMING_ENABLED: ${LC_ASR_STREAMING_ENABLED:-未設定}"
echo "GOOGLE_APPLICATION_CREDENTIALS: ${GOOGLE_APPLICATION_CREDENTIALS:-未設定}"
echo ""

echo "=========================================="

