#!/bin/bash
# LibertyCall: イントロテンプレート（000-002）診断スクリプト

echo "=========================================="
echo "LibertyCall: イントロテンプレート診断"
echo "=========================================="
echo ""

# 1. ログ確認（queued/sent/error）
echo "【1】ログ確認: intro=queued/sent/error"
echo "----------------------------------------"
LOG_FILES="/tmp/event_listener.log /tmp/gateway_*.log"
for log_file in $LOG_FILES; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        echo ""
        echo "📄 $log_file:"
        grep -E "intro=(queued|sent|error|skipped)" "$log_file" 2>/dev/null | tail -n 10
        if [ $? -ne 0 ]; then
            echo "  (該当ログなし)"
        fi
    fi
done
echo ""

# 2. テンプレート定義確認
echo "【2】テンプレート定義確認: /opt/libertycall/config/clients/001/templates.json"
echo "----------------------------------------"
if [ -f "/opt/libertycall/config/clients/001/templates.json" ]; then
    echo "✅ ファイル存在"
    echo ""
    echo "000-002 の定義:"
    cat /opt/libertycall/config/clients/001/templates.json | python3 -m json.tool 2>/dev/null | grep -A 10 '"000-002"'
    if [ $? -ne 0 ]; then
        echo "  (000-002 が見つかりません)"
        echo ""
        echo "ファイル全体:"
        cat /opt/libertycall/config/clients/001/templates.json | python3 -m json.tool 2>/dev/null
    fi
else
    echo "❌ ファイルが存在しません"
fi
echo ""

# 3. 既存テンプレート（004/005）の動作確認
echo "【3】既存テンプレート（004/005）の動作確認"
echo "----------------------------------------"
echo "最近のログで 004/005 が送信されているか:"
for log_file in $LOG_FILES; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        echo ""
        echo "📄 $log_file:"
        grep -E "(TTS_SENT|template.*004|template.*005|templates=\[.*004|templates=\[.*005)" "$log_file" 2>/dev/null | tail -n 5
        if [ $? -ne 0 ]; then
            echo "  (該当ログなし)"
        fi
    fi
done
echo ""

# 4. テンプレート解決ログ確認
echo "【4】テンプレート解決ログ確認: 000-002"
echo "----------------------------------------"
for log_file in $LOG_FILES; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        echo ""
        echo "📄 $log_file:"
        grep -E "000-002|TEMPLATE.*000|synthesize.*000|resolve.*000" "$log_file" 2>/dev/null | tail -n 10
        if [ $? -ne 0 ]; then
            echo "  (該当ログなし)"
        fi
    fi
done
echo ""

# 5. on_call_start の呼び出し確認
echo "【5】on_call_start の呼び出し確認"
echo "----------------------------------------"
for log_file in $LOG_FILES; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        echo ""
        echo "📄 $log_file:"
        grep -E "on_call_start|CALL_START" "$log_file" 2>/dev/null | tail -n 5
        if [ $? -ne 0 ]; then
            echo "  (該当ログなし)"
        fi
    fi
done
echo ""

# 6. エラーログ確認
echo "【6】エラーログ確認"
echo "----------------------------------------"
for log_file in $LOG_FILES; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        echo ""
        echo "📄 $log_file:"
        grep -E "(ERROR|EXCEPTION|Traceback|intro=error)" "$log_file" 2>/dev/null | grep -E "(000-002|intro|on_call_start)" | tail -n 5
        if [ $? -ne 0 ]; then
            echo "  (該当エラーなし)"
        fi
    fi
done
echo ""

# 7. グローバルテンプレート定義確認（フォールバック用）
echo "【7】グローバルテンプレート定義確認"
echo "----------------------------------------"
GLOBAL_TEMPLATE_FILE="/opt/libertycall/libertycall/gateway/intent_rules.py"
if [ -f "$GLOBAL_TEMPLATE_FILE" ]; then
    echo "✅ ファイル存在"
    echo ""
    echo "TEMPLATE_CONFIG に 000-002 があるか:"
    grep -A 5 '"000-002"' "$GLOBAL_TEMPLATE_FILE" 2>/dev/null || echo "  (000-002 が見つかりません)"
else
    echo "❌ ファイルが存在しません"
fi
echo ""

# 8. サービス状態確認
echo "【8】サービス状態確認"
echo "----------------------------------------"
systemctl status libertycall.service --no-pager | head -n 10
echo ""

echo "=========================================="
echo "診断完了"
echo "=========================================="
echo ""
echo "📋 次のステップ:"
echo "1. 上記のログで「intro=queued」「intro=sent」が出ているか確認"
echo "2. 004/005 が鳴っているか確認（既存テンプレートの動作確認）"
echo "3. templates.json の 000-002 定義を確認"
echo "4. エラーログがあれば内容を確認"
echo ""

