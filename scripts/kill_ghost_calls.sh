#!/bin/bash
# ゴーストコール（存在しない通話）の検出と強制終了スクリプト

LOG_FILE="/opt/libertycall/logs/ghost_call_killer.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "=== ゴーストコール検出開始: $(date) ===" >> "$LOG_FILE"

# FreeSWITCHで実際に通話中のUUIDを取得
ACTIVE_UUIDS=$(fs_cli -x "show channels" 2>/dev/null | grep -oP 'uuid: \K[0-9a-f-]+' || echo "")

# 実行中のgatewayプロセスとそのUUIDを取得
for PID in $(pgrep -f "realtime_gateway.py"); do
    # コマンドラインからUUIDを抽出
    CMDLINE=$(ps -p $PID -o cmd= 2>/dev/null)
    UUID=$(echo "$CMDLINE" | grep -oP '\-\-uuid\s+\K[0-9a-f-]+' || echo "")
    
    if [ -z "$UUID" ]; then
        echo "警告: PID $PID のUUIDを取得できませんでした" >> "$LOG_FILE"
        continue
    fi
    
    # FreeSWITCHに通話が存在するかチェック
    if echo "$ACTIVE_UUIDS" | grep -q "$UUID"; then
        echo "正常: PID $PID (UUID: $UUID) - FreeSWITCHに通話が存在します" >> "$LOG_FILE"
    else
        # ゴーストコール検出！
        ELAPSED=$(ps -p $PID -o etime= 2>/dev/null | tr -d ' ')
        echo "ゴーストコール検出: PID $PID (UUID: $UUID) 実行時間: $ELAPSED" >> "$LOG_FILE"
        echo "  強制終了します..." >> "$LOG_FILE"
        
        # プロセスを強制終了（SIGTERM → SIGKILL）
        kill -TERM $PID 2>/dev/null
        sleep 2
        
        # まだ生きていたらSIGKILL
        if ps -p $PID > /dev/null 2>&1; then
            echo "  SIGTERM失敗、SIGKILLで強制終了します" >> "$LOG_FILE"
            kill -KILL $PID 2>/dev/null
        fi
        
        echo "  ゴーストコール終了完了: PID $PID" >> "$LOG_FILE"
    fi
done

echo "=== ゴーストコール検出完了: $(date) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
