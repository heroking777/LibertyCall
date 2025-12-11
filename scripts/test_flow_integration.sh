#!/bin/bash
# 会話フロー統合テストスクリプト
# flow_tester.ts を呼び出し、全主要インテントを自動テスト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$PROJECT_ROOT/src/tools"

echo "============================================================"
echo "🧠 会話フロー統合テスト"
echo "============================================================"
echo ""

# TypeScript実行環境の確認
if ! command -v npx &> /dev/null; then
    echo "❌ エラー: npx が見つかりません。Node.js をインストールしてください。"
    exit 1
fi

# テスト対象インテントのリスト
INTENTS=(
    "INQUIRY"
    "SALES_CALL"
    "HANDOFF_REQUEST"
    "END_CALL"
    "NOT_HEARD"
    "GREETING"
    "HANDOFF_YES"
    "HANDOFF_NO"
)

# テスト結果を格納する配列
PASSED=0
FAILED=0
RESULTS=()

echo "📋 テスト対象インテント: ${INTENTS[*]}"
echo ""

# 各インテントをテスト
for INTENT in "${INTENTS[@]}"; do
    echo "----------------------------------------"
    echo "🧪 テスト: $INTENT"
    echo "----------------------------------------"
    
    # flow_tester.ts を実行
    if npx ts-node "$TOOLS_DIR/flow_tester.ts" --intent "$INTENT" --verbose 2>&1; then
        echo "✅ PASS: $INTENT"
        ((PASSED++))
        RESULTS+=("✅ $INTENT: PASS")
    else
        echo "❌ FAIL: $INTENT"
        ((FAILED++))
        RESULTS+=("❌ $INTENT: FAIL")
    fi
    
    echo ""
done

# 結果サマリー
echo "============================================================"
echo "📊 テスト結果サマリー"
echo "============================================================"
echo ""

for RESULT in "${RESULTS[@]}"; do
    echo "$RESULT"
done

echo ""
echo "合計: ${#INTENTS[@]} テスト"
echo "✅ 成功: $PASSED"
echo "❌ 失敗: $FAILED"

if [ $FAILED -eq 0 ]; then
    echo ""
    echo "🎉 すべてのテストが成功しました！"
    exit 0
else
    echo ""
    echo "⚠️  一部のテストが失敗しました。"
    exit 1
fi

