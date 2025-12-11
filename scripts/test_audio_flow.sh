#!/bin/bash
# 音声→ASR→会話→ログ検証までの一括自動テスト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$PROJECT_ROOT/src/tools"
TEST_AUDIO_DIR="$PROJECT_ROOT/tts_test"

echo "============================================================"
echo "🎧 LibertyCall ASR/TTS Flow Test"
echo "============================================================"
echo ""

# TypeScript実行環境の確認
if ! command -v npx &> /dev/null; then
    echo "❌ エラー: npx が見つかりません。Node.js をインストールしてください。"
    exit 1
fi

# Python実行環境の確認
if ! command -v python3 &> /dev/null; then
    echo "❌ エラー: python3 が見つかりません。"
    exit 1
fi

# テスト音声ディレクトリの確認
if [ ! -d "$TEST_AUDIO_DIR" ]; then
    echo "⚠️  警告: テスト音声ディレクトリが見つかりません: $TEST_AUDIO_DIR"
    echo "   空のディレクトリを作成します。"
    mkdir -p "$TEST_AUDIO_DIR"
fi

# 音声ファイルのリストを取得
AUDIO_FILES=()
if [ $# -eq 0 ]; then
    # 引数がない場合は tts_test/ 内のすべてのWAVファイルをテスト
    while IFS= read -r -d '' file; do
        AUDIO_FILES+=("$file")
    done < <(find "$TEST_AUDIO_DIR" -name "*.wav" -type f -print0 2>/dev/null)
else
    # 引数で指定されたファイル
    for arg in "$@"; do
        if [ -f "$arg" ]; then
            AUDIO_FILES+=("$arg")
        else
            echo "⚠️  警告: ファイルが見つかりません: $arg"
        fi
    done
fi

if [ ${#AUDIO_FILES[@]} -eq 0 ]; then
    echo "❌ エラー: テスト対象の音声ファイルが見つかりません。"
    echo "   使い方: $0 [audio_file1.wav] [audio_file2.wav] ..."
    echo "   または: $0  (tts_test/ 内のすべてのWAVファイルをテスト)"
    exit 1
fi

echo "📁 テスト対象: ${#AUDIO_FILES[@]} ファイル"
echo ""

# 各音声ファイルをテスト
for audio_file in "${AUDIO_FILES[@]}"; do
    echo "------------------------------------------------------------"
    echo "▶ $(basename "$audio_file")"
    echo "------------------------------------------------------------"
    
    # audio_flow_tester.ts を実行
    if npx ts-node "$TOOLS_DIR/audio_flow_tester.ts" "$audio_file" 2>&1; then
        echo "✅ テスト完了: $(basename "$audio_file")"
    else
        echo "❌ テスト失敗: $(basename "$audio_file")"
    fi
    
    echo ""
done

echo "============================================================"
echo "✅ すべての音声テストが完了しました。"
echo "============================================================"
echo ""

# ASR評価（WER計算）を実行
if [ -f "$PROJECT_ROOT/scripts/asr_eval.py" ]; then
    echo "📊 ASR評価（WER計算）を実行中..."
    echo ""
    python3 "$PROJECT_ROOT/scripts/asr_eval.py" || echo "⚠️  ASR評価でエラーが発生しました。"
    echo ""
fi

echo "📜 会話ログを確認:"
echo "   tail -f $PROJECT_ROOT/logs/conversation_trace.log"
echo ""

