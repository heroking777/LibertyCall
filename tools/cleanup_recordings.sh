#!/bin/bash
# 録音ファイル30日ローテーション
RECORDING_DIR="/opt/libertycall/recordings"
RETENTION_DAYS=30
LOG="/opt/libertycall/logs/cleanup_recordings.log"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] cleanup start" >> "$LOG"

# 30日超のwav/jsonlを削除
count=$(find "$RECORDING_DIR" -type f \( -name '*.wav' -o -name '*.jsonl' \) -mtime +${RETENTION_DAYS} | wc -l)
find "$RECORDING_DIR" -type f \( -name '*.wav' -o -name '*.jsonl' \) -mtime +${RETENTION_DAYS} -delete

# 空ディレクトリを削除
find "$RECORDING_DIR" -mindepth 2 -type d -empty -delete

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] cleanup done deleted=$count" >> "$LOG"
