#!/bin/bash
# LibertyCall: Gateway ログのリアルタイム監視スクリプト

echo "=========================================="
echo "LibertyCall: Gateway ログ監視"
echo "=========================================="
echo ""

# 最新のログファイルを特定
LATEST=$(ls -1t /tmp/gateway_*.log 2>/dev/null | head -n 1)

if [ -z "$LATEST" ]; then
    echo "❌ gateway_*.log ファイルが見つかりません"
    echo "通話を発信してください"
    exit 1
fi

echo "📄 監視対象: $LATEST"
echo ""
echo "監視キーワード:"
echo "  - DEBUG_PRINT"
echo "  - _queue_initial_audio_sequence"
echo "  - RTP_RECV"
echo "  - init"
echo "  - on_call_start"
echo "  - tts/TTS"
echo ""
echo "=========================================="
echo "リアルタイム監視開始（Ctrl+C で終了）"
echo "=========================================="
echo ""

tail -f "$LATEST" | grep --line-buffered -E "DEBUG_PRINT|_queue_initial_audio_sequence|RTP_RECV|init|on_call_start|tts|TTS|intro="

