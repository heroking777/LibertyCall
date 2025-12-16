#!/bin/bash
# 通話開始直後に実行する確認スクリプト

echo "=== 通話状態確認 ==="
echo ""

echo "1. チャネル状態:"
fs_cli -x "show channels" 2>/dev/null
echo ""

echo "2. 最新のFreeSWITCHログ（SIP関連）:"
sudo tail -n 50 /usr/local/freeswitch/log/freeswitch.log | grep -E "INVITE|180|200|BYE|58304073|7003|rtp_stream" | tail -20
echo ""

echo "3. 最新のLibertyCallログ:"
sudo journalctl -u libertycall -n 30 --no-pager | grep -E "RTP_RECV|ERROR|WARNING" | tail -10
echo ""

echo "4. アクティブなセッション:"
fs_cli -x "show calls" 2>/dev/null
echo ""

