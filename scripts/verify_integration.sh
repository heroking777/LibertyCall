#!/bin/bash
# 全体連携検証スクリプト
# ASR→AI→WER→ダッシュボードの一連の流れを検証

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================================"
echo "🔍 全体連携検証（ASR→AI→WER→ダッシュボード）"
echo "============================================================"
echo ""

# カラー出力用
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0

# テスト関数
test_step() {
    local step_name="$1"
    local command="$2"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 $step_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if eval "$command" > /tmp/integration_test_output.log 2>&1; then
        echo -e "${GREEN}✅ PASS${NC}: $step_name"
        cat /tmp/integration_test_output.log | tail -5
        ((PASSED++))
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}: $step_name"
        cat /tmp/integration_test_output.log | tail -10
        ((FAILED++))
        return 1
    fi
}

# 1. 音声ファイルの確認
test_step "音声ファイルの確認" \
    "ls -lh $PROJECT_ROOT/tts_test/*.wav | head -3"

# 2. 期待テキストファイルの確認
test_step "期待テキストファイルの確認" \
    "test -f $PROJECT_ROOT/tts_test/reference_texts.json && cat $PROJECT_ROOT/tts_test/reference_texts.json | head -5"

# 3. ASR認識テスト
test_step "ASR認識テスト（004_moshimoshi.wav）" \
    "cd $PROJECT_ROOT && python3 scripts/test_audio_asr.py tts_test/004_moshimoshi.wav"

# 4. 認識結果の保存確認
test_step "認識結果の保存確認" \
    "test -f $PROJECT_ROOT/tts_test/results/004_moshimoshi.txt && cat $PROJECT_ROOT/tts_test/results/004_moshimoshi.txt"

# 5. AI処理テスト
test_step "AI処理テスト" \
    "cd $PROJECT_ROOT && python3 scripts/test_ai_response.py 'もしもし' TEST_CALL"

# 6. WER評価実行
test_step "WER評価実行" \
    "cd $PROJECT_ROOT && python3 scripts/asr_eval.py --threshold 0.10 --no-json"

# 7. WER評価結果JSONの確認
test_step "WER評価結果JSONの確認" \
    "test -f $PROJECT_ROOT/logs/asr_eval_results.json && cat $PROJECT_ROOT/logs/asr_eval_results.json | head -20"

# 8. バックエンドAPIのインポート確認
test_step "バックエンドAPIのインポート確認" \
    "cd $PROJECT_ROOT && python3 -c 'import sys; sys.path.insert(0, \".\"); from console_backend.routers.audio_tests import router; print(\"OK\")'"

# 9. FastAPIアプリの確認
test_step "FastAPIアプリの確認" \
    "cd $PROJECT_ROOT && python3 -c 'import sys; sys.path.insert(0, \".\"); from console_backend.main import app; routes = [r.path for r in app.routes if hasattr(r, \"path\") and \"/audio_tests\" in r.path]; print(\"Routes found:\", len(routes))'"

# 10. フロントエンドファイルの確認
test_step "フロントエンドファイルの確認" \
    "test -f $PROJECT_ROOT/frontend/src/pages/AudioTestDashboard.jsx && grep -q 'AudioTestDashboard' $PROJECT_ROOT/frontend/src/pages/AudioTestDashboard.jsx"

# 11. 統合テスト（音声→ASR→AI）
test_step "統合テスト（音声→ASR→AI）" \
    "cd $PROJECT_ROOT && npx ts-node src/tools/audio_flow_tester.ts tts_test/004_moshimoshi.wav 2>&1 | grep -E '(認識結果|PHASE=|✅|❌)' | head -5"

# 結果サマリー
echo ""
echo "============================================================"
echo "📊 検証結果サマリー"
echo "============================================================"
echo ""
echo -e "${GREEN}✅ 成功: $PASSED${NC}"
echo -e "${RED}❌ 失敗: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 すべての検証が成功しました！${NC}"
    echo ""
    echo "次のステップ:"
    echo "  1. バックエンドAPIを起動: uvicorn console_backend.main:app --reload --host 0.0.0.0 --port 8000"
    echo "  2. フロントエンドを起動: cd frontend && npm run dev"
    echo "  3. ブラウザでアクセス: http://localhost:5173/console/audio-tests"
    exit 0
else
    echo -e "${RED}⚠️  一部の検証が失敗しました。${NC}"
    echo "詳細は上記の出力を確認してください。"
    exit 1
fi

