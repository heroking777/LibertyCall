#!/bin/bash
# LibertyCall: プロセスとログの確認スクリプト

echo "=========================================="
echo "LibertyCall: プロセスとログ確認"
echo "=========================================="
echo ""

# 1. 実行中プロセスの確認
echo "【1】実行中プロセスの確認"
echo "----------------------------------------"
ps aux | grep -E "libertycall|realtime_gateway|gateway|python.*gateway" | grep -v grep
if [ $? -ne 0 ]; then
    echo "❌ プロセスが見つかりません"
fi
echo ""

# 2. systemd サービスの状態確認
echo "【2】systemd サービスの状態確認"
echo "----------------------------------------"
systemctl status libertycall.service --no-pager 2>/dev/null | head -n 30
echo ""

# 3. journalctl ログの確認（最新100行）
echo "【3】journalctl ログの確認（最新100行）"
echo "----------------------------------------"
journalctl -u libertycall.service -n 100 --no-pager 2>/dev/null | tail -n 50
if [ $? -ne 0 ]; then
    echo "❌ journalctl でログを取得できませんでした"
fi
echo ""

# 4. ファイルログの確認
echo "【4】ファイルログの確認"
echo "----------------------------------------"
for log_file in /tmp/event_listener.log /tmp/gateway_*.log; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        echo ""
        echo "📄 $log_file:"
        echo "  サイズ: $(stat -c%s "$log_file" 2>/dev/null || echo "N/A") bytes"
        echo "  最終更新: $(stat -c%y "$log_file" 2>/dev/null || echo "N/A")"
        echo "  最新5行:"
        tail -n 5 "$log_file" 2>/dev/null || echo "  (読み込み失敗)"
    fi
done
echo ""

# 5. DEBUG_PRINT の確認（診断用）
echo "【5】DEBUG_PRINT の確認（診断用）"
echo "----------------------------------------"
echo "journalctl から DEBUG_PRINT を検索:"
journalctl -u libertycall.service -n 500 --no-pager 2>/dev/null | grep "DEBUG_PRINT" | tail -n 20
if [ $? -ne 0 ]; then
    echo "  (DEBUG_PRINT が見つかりません)"
fi
echo ""

echo "ファイルログから DEBUG_PRINT を検索:"
for log_file in /tmp/event_listener.log /tmp/gateway_*.log; do
    if [ -f "$log_file" ] || ls $log_file 2>/dev/null | grep -q .; then
        grep "DEBUG_PRINT" "$log_file" 2>/dev/null | tail -n 10
    fi
done
echo ""

# 6. コードファイルの確認
echo "【6】コードファイルの確認"
echo "----------------------------------------"
echo "on_call_start メソッドの存在確認:"
grep -n "def on_call_start" /opt/libertycall/libertycall/gateway/ai_core.py | head -n 1
if [ $? -ne 0 ]; then
    echo "  ❌ on_call_start メソッドが見つかりません"
else
    echo "  ✅ on_call_start メソッドが見つかりました"
fi
echo ""

echo "intro=queued の存在確認:"
grep -n "intro=queued" /opt/libertycall/libertycall/gateway/ai_core.py | head -n 1
if [ $? -ne 0 ]; then
    echo "  ❌ intro=queued が見つかりません"
else
    echo "  ✅ intro=queued が見つかりました"
fi
echo ""

echo "Phase set to INTRO の存在確認:"
grep -n "Phase set to INTRO" /opt/libertycall/libertycall/gateway/ai_core.py | head -n 1
if [ $? -ne 0 ]; then
    echo "  ❌ Phase set to INTRO が見つかりません"
else
    echo "  ✅ Phase set to INTRO が見つかりました"
fi
echo ""

echo "=========================================="
echo "確認完了"
echo "=========================================="
echo ""
echo "📋 次のステップ:"
echo "1. 上記の結果を確認してください"
echo "2. DEBUG_PRINT が出ているか確認してください"
echo "3. プロセスが正しく起動しているか確認してください"
echo "4. ログの出力先が正しいか確認してください"
echo ""

