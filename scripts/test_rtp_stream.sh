#!/bin/bash
# RTPストリーム確認スクリプト

echo "=========================================="
echo "RTPストリーム確認"
echo "=========================================="
echo ""

echo "1. realtime_gateway.py プロセス確認"
echo "----------------------------------------"
if ps aux | grep "realtime_gateway.py" | grep -v grep > /dev/null; then
    echo "✅ realtime_gateway.py 実行中"
    ps aux | grep "realtime_gateway.py" | grep -v grep | head -1
else
    echo "❌ realtime_gateway.py 停止中"
fi
echo ""

echo "2. ポート7002のリッスン確認"
echo "----------------------------------------"
if sudo netstat -ulnp 2>/dev/null | grep -q ":7002"; then
    echo "✅ ポート7002でリッスン中"
    sudo netstat -ulnp 2>/dev/null | grep ":7002"
else
    echo "❌ ポート7002でリッスンしていません"
fi
echo ""

echo "3. FreeSWITCH設定確認"
echo "----------------------------------------"
if grep -q "uuid_rtp_stream" /opt/libertycall/freeswitch/dialplan/default.xml; then
    echo "✅ uuid_rtp_stream 設定あり"
    grep -A 1 "uuid_rtp_stream" /opt/libertycall/freeswitch/dialplan/default.xml | head -2
else
    echo "❌ uuid_rtp_stream 設定なし"
fi
echo ""

echo "4. 次回着信テスト時の確認コマンド"
echo "----------------------------------------"
echo "ターミナル1: ログ監視"
echo "  tail -f /tmp/gateway_realtime.log | grep -E 'RTP_RECV|ASR_DEBUG|ASR_HOOK'"
echo ""
echo "ターミナル2: ネットワーク監視"
echo "  sudo tcpdump -i any -n udp port 7002 -c 20"
echo ""
echo "ターミナル3: チャンネル確認"
echo "  sudo fs_cli -x 'show channels'"
echo ""

echo "=========================================="

