#!/bin/bash
LOG=/opt/libertycall/training_data/health.log
ALERT_MSG=""

add_alert() {
    echo "$(date): ALERT - $1" >> "$LOG"
    ALERT_MSG="${ALERT_MSG}$1\n"
}

# 1. FreeSWITCH
if ! fs_cli -x "status" > /dev/null 2>&1; then
    echo "$(date): WARN - FreeSWITCH down, restarting" >> "$LOG"
    sudo systemctl restart freeswitch
    sleep 15
    if ! fs_cli -x "status" > /dev/null 2>&1; then
        sleep 10
        if ! fs_cli -x "status" > /dev/null 2>&1; then
            add_alert "FreeSWITCH restart FAILED"
        fi
    fi
fi

# 2. ws_sink (port 9000) - systemd管理
if ! ss -tlnp | grep -q ":9000 "; then
    echo "$(date): WARN - ws_sink (9000) down, restarting via systemd" >> "$LOG"
    sudo systemctl restart ws-sink
    sleep 10
    if ! ss -tlnp | grep -q ":9000 "; then
        add_alert "ws_sink restart FAILED"
    fi
fi

# 3. SIP gateway
GW_STATE=$(fs_cli -x "sofia status gateway rakuten" 2>/dev/null | grep "^State" | awk '{print $2}')
if [ "$GW_STATE" != "REGED" ] && [ "$GW_STATE" != "" ]; then
    echo "$(date): WARN - gateway rakuten state=$GW_STATE, rescan" >> "$LOG"
    fs_cli -x "sofia profile lab_open rescan reloadxml" > /dev/null 2>&1
    sleep 10
    GW_STATE2=$(fs_cli -x "sofia status gateway rakuten" 2>/dev/null | grep "^State" | awk '{print $2}')
    if [ "$GW_STATE2" != "REGED" ]; then
        add_alert "gateway rakuten state=$GW_STATE2 after rescan"
    fi
fi

# 4. ws_sink メモリ異常チェック - systemd管理
WS_PID=$(pgrep -f "ws_sink.py" | head -1)
if [ -n "$WS_PID" ]; then
    MEM=$(ps -o rss= -p "$WS_PID" 2>/dev/null | tr -d ' ')
    if [ -n "$MEM" ] && [ "$MEM" -gt 2097152 ]; then
        echo "$(date): WARN - ws_sink memory ${MEM}KB > 2GB, restarting via systemd" >> "$LOG"
        sudo systemctl restart ws-sink
        sleep 10
        if ! ss -tlnp | grep -q ":9000 "; then
            add_alert "ws_sink memory restart FAILED (was ${MEM}KB)"
        fi
    fi
fi

# 5. ディスク使用率チェック
DISK_USE=$(df / | awk 'NR==2{print int($5)}')
if [ "$DISK_USE" -gt 90 ]; then
    add_alert "disk usage ${DISK_USE}%"
fi

# メール通知（復旧失敗時のみ）
if [ -n "$ALERT_MSG" ]; then
    echo -e "$(date)\nサーバー障害検知（自動復旧失敗）:\n${ALERT_MSG}\nホスト: $(hostname)" | /opt/libertycall/venv/bin/python3 /opt/libertycall/send_alert.py "[LibertyCall ALERT] 障害検知（復旧失敗）"
fi

# 正常時
if [ -z "$ALERT_MSG" ]; then
    sed -i '/^.*: OK$/d' "$LOG"
    echo "$(date +%H:%M): OK" >> "$LOG"
fi

# 5. syslog肥大化防止
SYSLOG_SIZE=$(sudo du -sm /var/log/syslog 2>/dev/null | awk '{print $1}')
if [ "${SYSLOG_SIZE:-0}" -gt 500 ]; then
    sudo truncate -s 0 /var/log/syslog
    echo "$(date): WARN - syslog truncated (was ${SYSLOG_SIZE}MB)" >> "$LOG"
    add_alert "syslog truncated (${SYSLOG_SIZE}MB)"
fi
SYSLOG1_SIZE=$(sudo du -sm /var/log/syslog.1 2>/dev/null | awk '{print $1}')
if [ "${SYSLOG1_SIZE:-0}" -gt 500 ]; then
    sudo truncate -s 0 /var/log/syslog.1
    echo "$(date): WARN - syslog.1 truncated (was ${SYSLOG1_SIZE}MB)" >> "$LOG"
fi
