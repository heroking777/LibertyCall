#!/bin/bash
# SQLite DBの日次バックアップ
BACKUP_DIR="/opt/libertycall/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
DB_PATH="/opt/call_console.db"

if [ -f "$DB_PATH" ]; then
    /usr/bin/python3 -c "
import sqlite3, shutil
src = sqlite3.connect('$DB_PATH')
dst = sqlite3.connect('${BACKUP_DIR}/call_console_${DATE}.db')
src.backup(dst)
src.close()
dst.close()
print('backup ok')
"
    echo "$(date): DB backup created: call_console_${DATE}.db" >> /opt/libertycall/training_data/health.log
    
    # 7日以上古いバックアップを削除
    find "$BACKUP_DIR" -name "call_console_*.db" -mtime +7 -delete
else
    echo "$(date): ERROR - DB not found: $DB_PATH" >> /opt/libertycall/training_data/health.log
fi
