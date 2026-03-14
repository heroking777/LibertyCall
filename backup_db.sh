#!/bin/bash
# 日次バックアップ（DB + 設定ファイル）
BACKUP_DIR="/opt/libertycall/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
DB_PATH="/opt/call_console.db"
LOG="/opt/libertycall/training_data/health.log"

# SQLite DBバックアップ
if [ -f "$DB_PATH" ]; then
    /usr/bin/python3 -c "
import sqlite3
src = sqlite3.connect('$DB_PATH')
dst = sqlite3.connect('${BACKUP_DIR}/call_console_${DATE}.db')
src.backup(dst)
src.close()
dst.close()
print('backup ok')
"
    echo "$(date): DB backup created: call_console_${DATE}.db" >> "$LOG"
else
    echo "$(date): ERROR - DB not found: $DB_PATH" >> "$LOG"
fi

# dialogue_config.jsonバックアップ（全クライアント）
for config in /opt/libertycall/clients/*/config/dialogue_config.json; do
    if [ -f "$config" ]; then
        client_id=$(echo "$config" | grep -oP 'clients/\K[^/]+')
        cp "$config" "${BACKUP_DIR}/dialogue_config_${client_id}_${DATE}.json"
    fi
done
echo "$(date): Config backup completed" >> "$LOG"

# 7日以上古いバックアップを削除
find "$BACKUP_DIR" -name "call_console_*.db" -mtime +7 -delete
find "$BACKUP_DIR" -name "dialogue_config_*.json" -mtime +7 -delete
