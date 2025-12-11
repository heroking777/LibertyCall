#!/bin/bash
# Gatewayのログファイルに最新テンプレート出力を監視（tail実行）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/conversation_trace.log"

echo "============================================================"
echo "🔍 Gateway 会話トレースログ監視"
echo "============================================================"
echo ""
echo "監視対象: $LOG_FILE"
echo ""
echo "📝 ログフォーマット:"
echo "   [TIMESTAMP] PHASE=<phase> TEMPLATE=<template_ids> TEXT=<response_text>"
echo ""
echo "例:"
echo "   [2025-12-05T21:48:10] PHASE=ENTRY TEMPLATE=004 TEXT=もしもし。"
echo "   [2025-12-05T21:48:12] PHASE=QA TEMPLATE=006_SYS TEXT=ありがとうございます。システムについてですね。"
echo ""
echo "============================================================"
echo ""

# ログファイルが存在しない場合は作成
if [ ! -f "$LOG_FILE" ]; then
    echo "⚠️  ログファイルが存在しません。作成します: $LOG_FILE"
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    echo "✅ ログファイルを作成しました。"
    echo ""
fi

# tail -f でログを監視
echo "🔄 ログ監視を開始します（Ctrl+C で終了）..."
echo ""

tail -f "$LOG_FILE" | while IFS= read -r line; do
    # ログ行をパースして見やすく表示
    if [[ $line =~ ^\[([^\]]+)\]\ PHASE=([^\ ]+)\ TEMPLATE=([^\ ]+)\ TEXT=(.+)$ ]]; then
        timestamp="${BASH_REMATCH[1]}"
        phase="${BASH_REMATCH[2]}"
        template="${BASH_REMATCH[3]}"
        text="${BASH_REMATCH[4]}"
        
        # 色付きで表示
        echo -e "\033[1;34m[$timestamp]\033[0m \033[1;33mPHASE=$phase\033[0m \033[1;32mTEMPLATE=$template\033[0m"
        echo -e "  \033[1;36mTEXT:\033[0m $text"
        echo ""
    else
        # パースできない場合はそのまま表示
        echo "$line"
    fi
done

