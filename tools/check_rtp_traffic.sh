#!/bin/bash
# LibertyCall: RTP トラフィック確認スクリプト

echo "=========================================="
echo "LibertyCall: RTP トラフィック確認"
echo "=========================================="
echo ""
echo "📋 確認項目:"
echo "1. ポート7002を掴んでいるプロセス"
echo "2. RTP パケットの受信状況（tcpdump）"
echo ""
echo "=========================================="
echo ""

# 1. ポート7002を掴んでいるプロセス確認
echo "【1】ポート7002を掴んでいるプロセス:"
sudo ss -lunp | grep ":7002"
if [ $? -ne 0 ]; then
    echo "  ❌ ポート7002を掴んでいるプロセスが見つかりません"
fi
echo ""

# 2. tcpdump で RTP パケットを監視
echo "【2】RTP パケット監視（tcpdump）:"
echo "  通話を発信してください"
echo "  Ctrl+C で終了"
echo ""
echo "=========================================="
echo ""

sudo tcpdump -ni any udp port 7002 -vv

