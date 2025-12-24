#!/bin/bash
# ASRテスト用ログ監視スクリプト（ワンライナー対応）

echo "=========================================="
echo "ASRテスト用ログ監視"
echo "=========================================="
echo ""
echo "監視対象:"
echo "  - FreeSWITCHログ: playback, ASR, hangup"
echo "  - Gatewayログ: ASRHandler, GoogleStreamingASR"
echo ""
echo "Ctrl+C で終了"
echo "=========================================="
echo ""

# FreeSWITCHログ監視
sudo tail -Fn0 /usr/local/freeswitch/log/freeswitch.log | grep -E "playback|ASR|WAIT|hangup|CHANNEL_ANSWER|CHANNEL_HANGUP" &
FS_PID=$!

# Gatewayログ監視（最新のログファイルを監視）
LATEST_LOG=$(ls -t /tmp/gateway_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    tail -Fn0 "$LATEST_LOG" | grep -E "ASRHandler|GoogleStreamingASR|STREAMING_FEED|ASR DETECTED" &
    GW_PID=$!
else
    echo "⚠️  Gatewayログファイルが見つかりません（着信後に生成されます）"
    GW_PID=""
fi

# クリーンアップ関数
cleanup() {
    echo ""
    echo "監視を終了します..."
    kill $FS_PID 2>/dev/null
    [ -n "$GW_PID" ] && kill $GW_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# 待機
wait

