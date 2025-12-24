#!/bin/bash
# gateway起動確認スクリプト

echo "=========================================="
echo "Gateway起動確認"
echo "=========================================="
echo ""

echo "1. gateway_event_listener確認"
echo "----------------------------------------"
if ps aux | grep gateway_event_listener | grep -v grep > /dev/null; then
    echo "✅ gateway_event_listener 実行中"
else
    echo "❌ gateway_event_listener 停止中"
fi
echo ""

echo "2. 最新のgatewayログ確認"
echo "----------------------------------------"
LATEST=$(ls -t /tmp/gateway_*.log 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "最新ログ: $LATEST"
    echo ""
    echo "起動ログ:"
    grep -E "INIT|Google Streaming ASR handler|streaming_enabled" "$LATEST" | head -5
    echo ""
    echo "ASR関連ログ:"
    grep -E "ASR_DEBUG|ASR_HOOK|ASRHandler" "$LATEST" | tail -5 || echo "  ASR関連ログなし"
else
    echo "  ❌ ログファイルが見つかりません"
fi
echo ""

echo "3. 次回着信時の確認ポイント"
echo "----------------------------------------"
echo "着信後、以下を確認:"
echo "  ps aux | grep realtime_gateway | grep -v grep"
echo ""
echo "期待されるログ:"
echo "  [INIT] Google Streaming ASR handler available"
echo "  [ASR_HOOK] ASR handler on_incoming_call() executed"
echo "  [ASRHandler] Google Streaming ASR started"
echo ""

echo "=========================================="

