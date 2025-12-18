#!/bin/bash
# RTP接続検証スクリプト
# 使用方法: ./scripts/verify_rtp_connection.sh <UUID>

UUID="$1"

if [ -z "$UUID" ]; then
    echo "使用方法: $0 <UUID>"
    echo ""
    echo "UUIDを取得するには:"
    echo "  grep 'CHANNEL_EXECUTE_COMPLETE' /tmp/event_listener.log | tail -1"
    exit 1
fi

echo "=== RTP接続検証: UUID=$UUID ==="
echo ""

# 1. Event Socketログ確認
echo "【1】Event Socketログ確認"
echo "----------------------------------------"
grep -E "handle_call|get_rtp_port" /tmp/event_listener.log | grep "$UUID" | tail -10
echo ""

# 2. gatewayログ確認
GATEWAY_LOG="/tmp/gateway_${UUID}.log"
if [ -f "$GATEWAY_LOG" ]; then
    echo "【2】Gatewayログ確認"
    echo "----------------------------------------"
    grep -E "RTP_BIND|RTP_RECV|RTP_RECV_RAW" "$GATEWAY_LOG" | tail -20
    echo ""
else
    echo "【2】Gatewayログ確認"
    echo "----------------------------------------"
    echo "警告: $GATEWAY_LOG が見つかりません"
    echo ""
fi

# 3. FreeSWITCH側確認
echo "【3】FreeSWITCH側ポート確認"
echo "----------------------------------------"
echo "remote_media_ip:"
fs_cli -x "uuid_getvar $UUID remote_media_ip" 2>/dev/null || echo "取得失敗"
echo ""
echo "remote_media_port:"
fs_cli -x "uuid_getvar $UUID remote_media_port" 2>/dev/null || echo "取得失敗"
echo ""
echo "uuid_media_stats:"
fs_cli -x "uuid_media_stats $UUID" 2>/dev/null || echo "取得失敗"
echo ""

# 4. netstatでポート確認
RTP_PORT=$(fs_cli -x "uuid_getvar $UUID remote_media_port" 2>/dev/null | grep -v "^$" | tail -1)
if [ -n "$RTP_PORT" ] && [ "$RTP_PORT" != "-ERR" ]; then
    echo "【4】netstatでポート確認 (port=$RTP_PORT)"
    echo "----------------------------------------"
    netstat -anu | grep ":$RTP_PORT " || echo "ポート $RTP_PORT でLISTENしているプロセスが見つかりません"
    echo ""
else
    echo "【4】netstatでポート確認"
    echo "----------------------------------------"
    echo "警告: RTPポートが取得できませんでした"
    echo ""
fi

echo "=== 検証完了 ==="

