#!/bin/bash
# 音声リスト同期と音声ファイル生成を実行するスクリプト

set -e

cd /opt/libertycall

echo "=========================================="
echo "1️⃣ 音声リストを修正＆同期"
echo "=========================================="
python3 scripts/sync_voice_assets.py --yes

echo ""
echo "=========================================="
echo "2️⃣ 不足音声ファイルを自動生成"
echo "=========================================="
export GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json
make audio-all || python3 scripts/generate_no_input_audio.py

echo ""
echo "=========================================="
echo "3️⃣ 結果確認"
echo "=========================================="
echo "音声ファイル:"
ls -lh clients/000/audio/template_1*.wav 2>/dev/null || echo "  (音声ファイルが見つかりません)"

echo ""
echo "レポート:"
if [ -f logs/audio_sync_report.txt ]; then
    tail -20 logs/audio_sync_report.txt
else
    echo "  (レポートファイルが見つかりません)"
fi

echo ""
echo "✅ 完了"
