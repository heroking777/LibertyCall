#!/bin/bash

# 毎日0時に実行するクリーニングcron設定スクリプト

PROJECT_ROOT="/opt/libertycall"
CLEANUP_SCRIPT="${PROJECT_ROOT}/.venv/bin/python -m email_sender.list_cleaner"
LOG_FILE="/var/log/libertycall/cleanup.log"

echo "=== 毎日リストクリーニングcron設定 ==="

# cronジョブを設定
(crontab -l 2>/dev/null; echo "0 0 * * * ${CLEANUP_SCRIPT} >> ${LOG_FILE} 2>&1") | crontab -

echo "=== cron設定完了 ==="
echo "毎日0時にリストクリーニングを実行します"
echo "ログファイル: ${LOG_FILE}"
echo "現在のcron設定:"
crontab -l | grep list_cleaner
