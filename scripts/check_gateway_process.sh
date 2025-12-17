#!/bin/bash
# gatewayプロセスとログを確認するスクリプト

echo "=== Gateway プロセス確認 ==="
ps aux | grep realtime_gateway | grep -v grep || echo "  gatewayプロセスは実行されていません"
echo ""

echo "=== Event Socket Listener プロセス確認 ==="
ps aux | grep gateway_event_listener | grep -v grep || echo "  Event Socket Listenerは実行されていません"
echo ""

echo "=== 最新のgatewayログファイル ==="
ls -lt /tmp/gateway_*.log 2>/dev/null | head -5 || echo "  gatewayログファイルが見つかりません"
echo ""

if [ -n "$1" ]; then
    UUID=$1
    LOG_FILE="/tmp/gateway_${UUID}.log"
    if [ -f "$LOG_FILE" ]; then
        echo "=== Gateway ログ (UUID: $UUID) ==="
        tail -50 "$LOG_FILE"
    else
        echo "ログファイルが見つかりません: $LOG_FILE"
    fi
else
    echo "使用方法: $0 <UUID>"
    echo "例: $0 f299c64d-b492-44cd-8aad-3a7ef68d6763"
fi

