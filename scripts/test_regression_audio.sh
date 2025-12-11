#!/bin/bash
# 自動リグレッションモード
# 会話フローやテンプレート変更を検知して、変更箇所だけ音声テストを自動実行

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$PROJECT_ROOT/src/tools"
FLOW_JSON="$PROJECT_ROOT/docs/会話フロー_JSON構造版.json"
AUDIO_TEST_DIR="$PROJECT_ROOT/tts_test"
MAP_INTENT_SCRIPT="$PROJECT_ROOT/scripts/map_intent_audio.py"

echo "🔍 LibertyCall Regression Audio Test"
echo ""

# Gitリポジトリかどうか確認
if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "⚠️  警告: Gitリポジトリではありません。全テストを実行します。"
    echo ""
    exec "$SCRIPT_DIR/test_audio_flow.sh" "$@"
    exit $?
fi

# 比較対象のコミットを決定（環境変数または引数）
if [ -n "$GIT_DIFF_RANGE" ]; then
    # 範囲指定（例: HEAD~3..HEAD）
    COMPARE_FROM=$(echo "$GIT_DIFF_RANGE" | cut -d'.' -f1)
    COMPARE_TO=$(echo "$GIT_DIFF_RANGE" | cut -d'.' -f3)
    if [ -z "$COMPARE_TO" ]; then
        COMPARE_TO="HEAD"
    fi
    GIT_DIFF_CMD="git diff $COMPARE_FROM..$COMPARE_TO"
else
    # 単一コミット指定（デフォルト: HEAD~1）
    COMPARE_TO="${1:-HEAD~1}"
    GIT_DIFF_CMD="git diff $COMPARE_TO HEAD"
fi

echo "📊 変更検知: $COMPARE_TO との差分を確認中..."
echo ""

# 変更されたファイルを取得（関連ファイルのみ）
CHANGED_FILES=$($GIT_DIFF_CMD --name-only 2>/dev/null | grep -E 'docs/会話フロー_JSON構造版.json|docs/会話フロー一覧_修正版.md|libertycall/gateway/intent_rules.py|clients/.*/config/voice_lines.*\.json' || echo "")

if [ -z "$CHANGED_FILES" ]; then
    echo "✅ No relevant changes detected."
    exit 0
fi

echo "🧠 Detected changes:"
echo "$CHANGED_FILES" | sed 's/^/   /'
echo ""

# 差分から intent を抽出
echo "📝 差分からintentを抽出中..."
INTENTS_JSON=$(npx ts-node "$TOOLS_DIR/flow_diff_parser.ts" <<< "$($GIT_DIFF_CMD -- "$FLOW_JSON" 2>/dev/null || echo "")" 2>/dev/null || echo "[]")

# JSONからintentリストを取得
if command -v jq &> /dev/null; then
    INTENTS=$(echo "$INTENTS_JSON" | jq -r '.changedIntents[]' 2>/dev/null | tr '\n' ' ' || echo "")
else
    # jqがない場合の簡易パース
    INTENTS=$(echo "$INTENTS_JSON" | grep -oP '"changedIntents":\s*\[[^\]]*\]' | grep -oP '"[A-Z_]+"' | tr -d '"' | tr '\n' ' ' || echo "")
fi

if [ -z "$INTENTS" ]; then
    # intentが見つからない場合、全テストを実行
    echo "⚠️  関連するintentが見つかりませんでした。"
    echo "   全テストを実行します。"
    echo ""
    exec "$SCRIPT_DIR/test_audio_flow.sh" "$@"
    exit $?
fi

# intent に対応する wav ファイルを取得
echo "🎧 Running related audio tests:"
# intentリストをJSON配列形式に変換
INTENTS_ARRAY=$(echo "$INTENTS" | tr ' ' '\n' | sed 's/^/"/' | sed 's/$/"/' | tr '\n' ',' | sed 's/,$//' | sed 's/^/[/' | sed 's/$/]/')
AUDIO_FILES=$(python3 "$MAP_INTENT_SCRIPT" "$INTENTS_ARRAY" 2>/dev/null || echo "")

if [ -z "$AUDIO_FILES" ]; then
    echo "⚠️  関連する音声ファイルが見つかりませんでした。"
    echo "   全テストを実行します。"
    echo ""
    exec "$SCRIPT_DIR/test_audio_flow.sh" "$@"
    exit $?
fi

echo "$AUDIO_FILES" | tr ' ' '\n' | sed 's/^/   /'
echo ""

# 音声テスト実行
PASSED=0
FAILED=0

for audio_file in $AUDIO_FILES; do
    if [ ! -f "$audio_file" ]; then
        echo "⚠️  ファイルが見つかりません: $audio_file"
        continue
    fi
    
    # 音声テスト実行（簡潔な出力）
    TEST_OUTPUT=$(npx ts-node "$TOOLS_DIR/audio_flow_tester.ts" "$audio_file" 2>&1)
    TEST_RESULT=$(echo "$TEST_OUTPUT" | grep -E "PHASE=" | head -1 || echo "")
    
    if echo "$TEST_OUTPUT" | grep -q "✅" && [ -n "$TEST_RESULT" ]; then
        # PHASE情報を抽出して表示
        PHASE_INFO=$(echo "$TEST_RESULT" | sed 's/.*PHASE=\([^ ]*\).*TEMPLATE=\([^ ]*\).*/PHASE=\1 TEMPLATE=\2/' || echo "$TEST_RESULT")
        echo "🗣️  $(basename "$audio_file") → $PHASE_INFO ✅ PASS"
        ((PASSED++))
    else
        echo "🗣️  $(basename "$audio_file") → ❌ FAIL"
        ((FAILED++))
    fi
done

# 結果サマリー
echo ""
echo "============================================================"
echo "✅ PASS: $PASSED / $((PASSED + FAILED))"
if [ $FAILED -gt 0 ]; then
    echo "❌ FAIL: $FAILED / $((PASSED + FAILED))"
fi
echo "============================================================"

if [ $FAILED -eq 0 ]; then
    exit 0
else
    exit 1
fi

