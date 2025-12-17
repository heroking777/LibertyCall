#!/bin/bash
# 通話ログを監視するスクリプト

echo "=== 通話ログ監視スクリプト ==="
echo ""

# Event Socket Listener のログを確認
echo "[1] Event Socket Listener の最新ログ:"
echo "---"
tail -20 /tmp/event_listener.log 2>/dev/null | grep -E "EVENT:|get_rtp_port|handle_call|local_media_port" || echo "  ログが見つかりません"
echo ""

# 最新のgatewayログファイルを確認
LATEST_GATEWAY_LOG=$(ls -t /tmp/gateway_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_GATEWAY_LOG" ]; then
    UUID=$(basename "$LATEST_GATEWAY_LOG" | sed 's/gateway_\(.*\)\.log/\1/')
    echo "[2] 最新のGatewayログ (UUID: $UUID):"
    echo "---"
    tail -30 "$LATEST_GATEWAY_LOG" 2>/dev/null || echo "  ログが見つかりません"
    echo ""
    echo "リアルタイム監視: tail -f $LATEST_GATEWAY_LOG"
else
    echo "[2] Gatewayログファイルが見つかりません"
    echo "   通話が開始されると /tmp/gateway_<UUID>.log が生成されます"
fi
echo ""

# 実行中のgatewayプロセスを確認
echo "[3] 実行中のGatewayプロセス:"
ps aux | grep realtime_gateway | grep -v grep || echo "  Gatewayプロセスは実行されていません"
echo ""

# Event Socket Listener の状態確認
echo "[4] Event Socket Listener の状態:"
ps aux | grep gateway_event_listener | grep -v grep || echo "  Event Socket Listener は実行されていません"
echo ""

echo "=== 監視完了 ==="
echo ""
echo "リアルタイム監視コマンド:"
echo "  tail -f /tmp/event_listener.log"
if [ -n "$LATEST_GATEWAY_LOG" ]; then
    echo "  tail -f $LATEST_GATEWAY_LOG"
fi

