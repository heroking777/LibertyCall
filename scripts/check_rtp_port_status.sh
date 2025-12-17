#!/bin/bash
# RTPポート取得の状態を確認するスクリプト

echo "=== RTPポート取得システム状態確認 ==="
echo ""

# Event Socket Listener の状態
echo "[1] Event Socket Listener プロセス:"
if ps aux | grep -q "[g]ateway_event_listener"; then
    ps aux | grep "[g]ateway_event_listener" | awk '{print "   ✅ 実行中 (PID: " $2 ")"}'
else
    echo "   ❌ 実行されていません"
fi
echo ""

# FreeSWITCH Event Socket の状態
echo "[2] FreeSWITCH Event Socket:"
if sudo netstat -tlnp 2>/dev/null | grep -q ":8021"; then
    sudo netstat -tlnp 2>/dev/null | grep ":8021" | awk '{print "   ✅ " $4 " でLISTEN中"}'
else
    echo "   ❌ ポート8021がLISTENしていません"
fi
echo ""

# 最新のログ確認
echo "[3] 最新のログ（get_rtp_port関連）:"
if [ -f /tmp/event_listener.log ]; then
    echo "   --- 最後の10行 ---"
    tail -10 /tmp/event_listener.log | grep -E "get_rtp_port|local_media_port|RTPポート" | tail -5 || echo "   get_rtp_port関連のログが見つかりません"
else
    echo "   ❌ ログファイルが見つかりません"
fi
echo ""

# 接続テスト
echo "[4] fs_cli接続テスト:"
if /usr/bin/fs_cli -H localhost -P 8021 -p ClueCon -x "status" >/dev/null 2>&1; then
    echo "   ✅ localhost経由で接続成功"
else
    echo "   ❌ localhost経由で接続失敗"
fi
echo ""

# 最新のgatewayログ
LATEST_GATEWAY_LOG=$(ls -t /tmp/gateway_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_GATEWAY_LOG" ]; then
    UUID=$(basename "$LATEST_GATEWAY_LOG" | sed 's/gateway_\(.*\)\.log/\1/')
    echo "[5] 最新のGatewayログ (UUID: $UUID):"
    echo "   --- 最後の5行 ---"
    tail -5 "$LATEST_GATEWAY_LOG" 2>/dev/null || echo "   ログが見つかりません"
else
    echo "[5] Gatewayログファイルが見つかりません"
fi
echo ""

echo "=== 確認完了 ==="
echo ""
echo "次回の通話時に期待されるログ:"
echo "  DEBUG [get_rtp_port] 実行コマンド(試行1): /usr/bin/fs_cli -H localhost ..."
echo "  DEBUG [get_rtp_port] returncode=0, stdout=XXXX, stderr="
echo "  INFO [get_rtp_port] local_media_port=XXXX (試行1)"

