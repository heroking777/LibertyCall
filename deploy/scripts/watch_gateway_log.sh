#!/bin/bash
# Gateway ログ監視スクリプト
# Traceback を検出した場合に自動再起動を実行

LOG="/opt/libertycall/logs/gateway_stderr.log"
WATCHDOG_LOG="/opt/libertycall/logs/gateway_watchdog.log"

# ログファイルが存在しない場合はスキップ
if [ ! -f "$LOG" ]; then
    exit 0
fi

# Traceback を検出した場合
if grep -q "Traceback" "$LOG"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S'): Restarting gateway due to error (Traceback detected)" >> "$WATCHDOG_LOG"
    systemctl restart gateway
    # 検出したTracebackをログに記録
    grep "Traceback" "$LOG" | tail -1 >> "$WATCHDOG_LOG"
fi
