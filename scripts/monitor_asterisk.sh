#!/bin/bash
# -*- coding: utf-8 -*-
# Asterisk監視スクリプト
# 定期的にAsteriskの状態をチェックし、異常があればログに記録

LOG_FILE="/opt/libertycall/logs/asterisk_monitor.log"
ASTERISK_PIDFILE="/var/run/asterisk/asterisk.pid"
ASTERISK_CTL="/var/run/asterisk/asterisk.ctl"

# ログディレクトリを作成
mkdir -p "$(dirname "$LOG_FILE")"

# ログ関数
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Asteriskプロセスの確認
check_asterisk_process() {
    if [ ! -f "$ASTERISK_PIDFILE" ]; then
        log_message "ERROR: Asterisk PID file not found: $ASTERISK_PIDFILE"
        return 1
    fi
    
    PID=$(cat "$ASTERISK_PIDFILE" 2>/dev/null)
    if [ -z "$PID" ]; then
        log_message "ERROR: Asterisk PID file is empty"
        return 1
    fi
    
    if ! ps -p "$PID" > /dev/null 2>&1; then
        log_message "ERROR: Asterisk process (PID: $PID) is not running"
        return 1
    fi
    
    return 0
}

# Asterisk制御ソケットの確認
check_asterisk_ctl() {
    if [ ! -S "$ASTERISK_CTL" ]; then
        log_message "ERROR: Asterisk control socket not found: $ASTERISK_CTL"
        return 1
    fi
    
    # Asterisk CLIに接続してコマンドを実行
    if ! sudo asterisk -rx "core show version" > /dev/null 2>&1; then
        log_message "ERROR: Cannot connect to Asterisk CLI"
        return 1
    fi
    
    return 0
}

# systemdサービスの確認
check_systemd_service() {
    SERVICE_STATUS=$(systemctl is-active asterisk.service 2>/dev/null)
    if [ "$SERVICE_STATUS" != "active" ] && [ "$SERVICE_STATUS" != "activating" ]; then
        log_message "ERROR: Asterisk systemd service is not active (status: $SERVICE_STATUS)"
        return 1
    fi
    
    # activating状態でも警告のみ（起動中は正常）
    if [ "$SERVICE_STATUS" = "activating" ]; then
        log_message "INFO: Asterisk systemd service is activating (startup in progress)"
    fi
    
    return 0
}

# メイン処理
main() {
    ERRORS=0
    
    if ! check_asterisk_process; then
        ERRORS=$((ERRORS + 1))
    fi
    
    if ! check_asterisk_ctl; then
        ERRORS=$((ERRORS + 1))
    fi
    
    if ! check_systemd_service; then
        ERRORS=$((ERRORS + 1))
    fi
    
    if [ $ERRORS -eq 0 ]; then
        log_message "OK: Asterisk is running normally"
        exit 0
    else
        log_message "WARNING: Found $ERRORS issue(s) with Asterisk"
        exit 1
    fi
}

main "$@"

