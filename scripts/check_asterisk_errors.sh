#!/bin/bash
# -*- coding: utf-8 -*-
# Asteriskエラーログ監視スクリプト
# 最近のエラーログをチェックし、重要なエラーがあれば通知

LOG_FILE="/opt/libertycall/logs/asterisk_error_check.log"
ASTERISK_MESSAGES_LOG="/var/log/asterisk/messages.log"
ASTERISK_FULL_LOG="/var/log/asterisk/full.log"
CHECK_INTERVAL="1 hour ago"

# ログディレクトリを作成
mkdir -p "$(dirname "$LOG_FILE")"

# ログ関数
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# エラーパターンのチェック
check_errors() {
    ERRORS_FOUND=0
    
    # messages.logからエラーを検索
    if [ -f "$ASTERISK_MESSAGES_LOG" ]; then
        ERROR_COUNT=$(sudo journalctl -u asterisk.service --since "$CHECK_INTERVAL" 2>/dev/null | grep -iE "(error|failed|timeout|refusing)" | wc -l)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            log_message "WARNING: Found $ERROR_COUNT error(s) in Asterisk messages log (last $CHECK_INTERVAL)"
            ERRORS_FOUND=$((ERRORS_FOUND + ERROR_COUNT))
        fi
    fi
    
    # 重要なエラーパターンをチェック
    CRITICAL_ERRORS=0
    
    # "Service has no ExecStart" エラー
    if sudo journalctl -u asterisk.service --since "$CHECK_INTERVAL" 2>/dev/null | grep -q "Service has no ExecStart"; then
        log_message "CRITICAL: Found 'Service has no ExecStart' error"
        CRITICAL_ERRORS=$((CRITICAL_ERRORS + 1))
    fi
    
    # "Failed with result 'timeout'" エラー
    if sudo journalctl -u asterisk.service --since "$CHECK_INTERVAL" 2>/dev/null | grep -q "Failed with result 'timeout'"; then
        log_message "CRITICAL: Found 'Failed with result timeout' error"
        CRITICAL_ERRORS=$((CRITICAL_ERRORS + 1))
    fi
    
    # "Unable to connect to remote asterisk" エラー
    if sudo journalctl -u asterisk.service --since "$CHECK_INTERVAL" 2>/dev/null | grep -q "Unable to connect to remote asterisk"; then
        log_message "CRITICAL: Found 'Unable to connect to remote asterisk' error"
        CRITICAL_ERRORS=$((CRITICAL_ERRORS + 1))
    fi
    
    if [ $CRITICAL_ERRORS -gt 0 ]; then
        log_message "CRITICAL: Found $CRITICAL_ERRORS critical error(s)"
        return 1
    fi
    
    if [ $ERRORS_FOUND -gt 0 ]; then
        log_message "WARNING: Found $ERRORS_FOUND error(s) in total"
        return 2
    fi
    
    log_message "OK: No critical errors found"
    return 0
}

# メイン処理
main() {
    check_errors
    EXIT_CODE=$?
    exit $EXIT_CODE
}

main "$@"

