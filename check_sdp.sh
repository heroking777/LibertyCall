#!/bin/bash
# SDP確認用スクリプト
# 実通話時に実行して、SDPにPCMUが含まれているか確認

echo "=== FreeSWITCH SDP確認スクリプト ==="
echo "新しい通話を開始してください..."
echo ""
echo "監視を開始します（Ctrl+Cで停止）..."
echo ""

# FreeSWITCHログからSDPとrtp_streamを監視
sudo tail -f /usr/local/freeswitch/log/freeswitch.log | grep --line-buffered -E "SDP|rtp_stream|PCMU|a=rtpmap" | while read line; do
    echo "[$(date '+%H:%M:%S')] $line"
    if echo "$line" | grep -q "a=rtpmap.*PCMU"; then
        echo "✓ PCMUコーデックが検出されました！"
    fi
done

