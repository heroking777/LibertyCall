#!/bin/bash
# 録音失敗検知（直近1時間のログから）
FAILURES=$(grep -c 'RECORDING.*failed' /tmp/ws_sink_debug.log 2>/dev/null || echo "0")
if [ "$FAILURES" -gt "0" ]; then
    echo "[ALERT] Recording failures detected: $FAILURES in recent log"
    echo "[ALERT] $(date -u '+%Y-%m-%dT%H:%M:%SZ') failures=$FAILURES" >> /opt/libertycall/logs/recording_alerts.log
fi
