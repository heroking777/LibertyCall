#!/bin/bash
# Gateway ログ監視 cron 設定スクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCH_SCRIPT="$SCRIPT_DIR/watch_gateway_log.sh"
CRON_JOB="* * * * * $WATCH_SCRIPT"

echo "=== Gateway ログ監視 cron 設定 ==="

# 1. スクリプトに実行権限を付与
echo "1. スクリプトに実行権限を付与中..."
chmod +x "$WATCH_SCRIPT"

# 2. cron に登録（既存のエントリを削除してから追加）
echo "2. cron に登録中..."
(crontab -l 2>/dev/null | grep -v "$WATCH_SCRIPT" || true; echo "$CRON_JOB") | crontab -

echo ""
echo "=== 現在の cron 設定 ==="
crontab -l | grep -A 1 -B 1 "watch_gateway_log" || echo "（該当エントリが見つかりません）"

echo ""
echo "=== セットアップ完了 ==="
echo "毎分、gateway_stderr.log をチェックし、Traceback を検出した場合に自動再起動します。"
echo "監視ログ: /opt/libertycall/logs/gateway_watchdog.log"
