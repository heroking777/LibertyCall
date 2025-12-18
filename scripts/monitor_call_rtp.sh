#!/bin/bash
# 通話中のRTP監視スクリプト
# 使用方法: ./scripts/monitor_call_rtp.sh

echo "=== RTP監視開始 ==="
echo "通話を発信してください..."
echo ""

# 最新のUUIDを取得
LATEST_UUID=$(grep "CHANNEL_EXECUTE_COMPLETE" /tmp/event_listener.log 2>/dev/null | tail -1 | grep -oP "UUID=\K[^ ]+" | head -1)

if [ -z "$LATEST_UUID" ]; then
    echo "通話が見つかりません。通話を発信してください。"
    exit 1
fi

echo "検出されたUUID: $LATEST_UUID"
echo ""

# リアルタイム監視
while true; do
    clear
    echo "=== RTP監視: UUID=$LATEST_UUID ==="
    echo "更新時刻: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    # Event Socketログ
    echo "【Event Socket】"
    grep -E "handle_call|get_rtp_port" /tmp/event_listener.log 2>/dev/null | grep "$LATEST_UUID" | tail -3
    echo ""
    
    # Gatewayログ
    GATEWAY_LOG="/tmp/gateway_${LATEST_UUID}.log"
    if [ -f "$GATEWAY_LOG" ]; then
        echo "【Gateway】"
        grep -E "RTP_BIND|RTP_RECV" "$GATEWAY_LOG" 2>/dev/null | tail -5
        echo ""
    fi
    
    # FreeSWITCH統計
    echo "【FreeSWITCH統計】"
    fs_cli -x "uuid_media_stats $LATEST_UUID" 2>/dev/null | head -10
    echo ""
    
    sleep 2
done

