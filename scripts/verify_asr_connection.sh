#!/bin/bash
# ASR接続確認スクリプト

echo "=========================================="
echo "ASR接続確認"
echo "=========================================="
echo ""

echo "1. realtime_gateway.py の修正確認"
echo "----------------------------------------"
if grep -q "ASR_HOOK.*ASR handler initialized" /opt/libertycall/gateway/realtime_gateway.py; then
    echo "✅ ASRハンドラー初期化コードが存在します"
else
    echo "❌ ASRハンドラー初期化コードが見つかりません"
fi

if grep -q "on_audio_chunk" /opt/libertycall/gateway/realtime_gateway.py; then
    echo "✅ on_audio_chunk呼び出しコードが存在します"
else
    echo "❌ on_audio_chunk呼び出しコードが見つかりません"
fi

echo ""
echo "2. asr_handler.py の確認"
echo "----------------------------------------"
if grep -q "def on_audio_chunk" /opt/libertycall/asr_handler.py; then
    echo "✅ on_audio_chunk メソッドが存在します"
else
    echo "❌ on_audio_chunk メソッドが見つかりません"
fi

if grep -q "def on_incoming_call" /opt/libertycall/asr_handler.py; then
    echo "✅ on_incoming_call メソッドが存在します"
else
    echo "❌ on_incoming_call メソッドが見つかりません"
fi

echo ""
echo "3. テスト実行準備"
echo "----------------------------------------"
echo "次のコマンドでテストを実行してください:"
echo ""
echo "  export GOOGLE_APPLICATION_CREDENTIALS=\"/opt/libertycall/key/google_tts.json\""
echo "  cd /opt/libertycall"
echo "  ./scripts/monitor_asr_test.sh"
echo ""
echo "着信後、以下のログが表示されれば成功:"
echo "  [ASR_HOOK] ASR handler initialized for call_id=..."
echo "  [ASR_HOOK] ASR handler on_incoming_call() executed"
echo "  [ASRHandler] Google Streaming ASR started"
echo "  STREAMING_FEED: idx=1 ..."
echo ""

