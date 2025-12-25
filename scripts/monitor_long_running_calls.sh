#!/bin/bash
# 長時間動作しているgatewayプロセスの監視・強制終了スクリプト

LOG_FILE="/opt/libertycall/logs/long_running_calls.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "=== 長時間動作プロセス監視開始: $(date) ===" >> "$LOG_FILE"

# 実行中のgatewayプロセスをチェック
for PID in $(pgrep -f "realtime_gateway.py"); do
    # 実行時間を秒単位で取得
    ELAPSED_SEC=$(ps -p $PID -o etimes= 2>/dev/null | tr -d ' ')
    
    if [ -z "$ELAPSED_SEC" ]; then
        continue
    fi
    
    ELAPSED_MIN=$((ELAPSED_SEC / 60))
    CMDLINE=$(ps -p $PID -o cmd= 2>/dev/null)
    UUID=$(echo "$CMDLINE" | grep -oP '\-\-uuid\s+\K[0-9a-f-]+' || echo "unknown")
    
    # 2時間（120分）以上: 強制終了
    if [ "$ELAPSED_MIN" -ge 120 ]; then
        echo "異常: PID $PID (UUID: $UUID) が2時間以上実行中 (${ELAPSED_MIN}分)" >> "$LOG_FILE"
        echo "  強制終了します..." >> "$LOG_FILE"
        
        kill -TERM $PID 2>/dev/null
        sleep 2
        
        if ps -p $PID > /dev/null 2>&1; then
            kill -KILL $PID 2>/dev/null
        fi
        
        echo "  強制終了完了: PID $PID" >> "$LOG_FILE"
        
    # 1時間（60分）以上: 警告
    elif [ "$ELAPSED_MIN" -ge 60 ]; then
        echo "警告: PID $PID (UUID: $UUID) が1時間以上実行中 (${ELAPSED_MIN}分)" >> "$LOG_FILE"
    fi
done

echo "=== 長時間動作プロセス監視完了: $(date) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
