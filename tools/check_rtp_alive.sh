#!/bin/bash
#
# LibertyCall RTP監視スクリプト
# gateway_*.log の [RTP_RECV_RAW] の更新時刻をチェックし、
# 5分以上更新がなければ service を再起動する
#

LOG_DIR="/tmp"
PATTERN="gateway_*.log"
TIMEOUT_MINUTES=5
TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))
SERVICE_NAME="service"
LOCK_FILE="/tmp/check_rtp_alive.lock"

# ロックファイルで重複実行を防止
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Previous check_rtp_alive.sh is still running (PID: $PID)"
        exit 0
    else
        rm -f "$LOCK_FILE"
    fi
fi

echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# ログファイルを検索
LATEST_TIME=0
LATEST_FILE=""

for log_file in $LOG_DIR/$PATTERN; do
    if [ ! -f "$log_file" ]; then
        continue
    fi
    
    # [RTP_RECV_RAW] を含む最後の行のタイムスタンプを取得
    # ログファイルの更新時刻（mtime）を使用
    if [ -f "$log_file" ]; then
        file_mtime=$(stat -c %Y "$log_file" 2>/dev/null || echo 0)
        
        # [RTP_RECV_RAW] を含む行の最終更新時刻を確認
        last_rtp_line=$(grep -h "\[RTP_RECV_RAW\]" "$log_file" 2>/dev/null | tail -1)
        
        if [ -n "$last_rtp_line" ]; then
            # ファイルの更新時刻を使用（より正確な監視のため）
            if [ "$file_mtime" -gt "$LATEST_TIME" ]; then
                LATEST_TIME=$file_mtime
                LATEST_FILE="$log_file"
            fi
        fi
    fi
done

CURRENT_TIME=$(date +%s)
TIME_DIFF=$((CURRENT_TIME - LATEST_TIME))

if [ "$LATEST_TIME" -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: No RTP log files found or no [RTP_RECV_RAW] entries found"
    # ログファイルが存在しない場合は、サービスが起動していない可能性がある
    # この場合は再起動しない（手動で確認が必要）
    exit 0
fi

if [ "$TIME_DIFF" -gt "$TIMEOUT_SECONDS" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: No RTP activity detected for ${TIMEOUT_MINUTES} minutes"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Last RTP activity: $(date -d "@$LATEST_TIME" '+%Y-%m-%d %H:%M:%S')"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting $SERVICE_NAME..."
    
    systemctl restart "$SERVICE_NAME"
    restart_status=$?
    
    if [ $restart_status -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Successfully restarted $SERVICE_NAME"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Failed to restart $SERVICE_NAME (exit code: $restart_status)"
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] OK: RTP activity detected (last: $(date -d "@$LATEST_TIME" '+%Y-%m-%d %H:%M:%S'), diff: ${TIME_DIFF}s)"
fi

exit 0

