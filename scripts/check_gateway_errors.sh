#!/bin/bash
# -*- coding: utf-8 -*-
# Gatewayエラーログ監視スクリプト
# GatewayログとAsteriskログを監視し、エラーや警告を検出

set -e

GATEWAY_LOG="/opt/libertycall/logs/realtime_gateway.log"
ASTERISK_LOG="/var/log/asterisk/full.log"
CHECK_LOG="/opt/libertycall/logs/gateway_error_check.log"
ALERT_EMAIL="${GATEWAY_ALERT_EMAIL:-}"  # 環境変数で設定可能
CHECK_INTERVAL="${GATEWAY_CHECK_INTERVAL:-300}"  # デフォルト5分

# ログディレクトリを作成
mkdir -p "$(dirname "$CHECK_LOG")"

# ログ関数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$CHECK_LOG"
}

# エラーパターン
ERROR_PATTERNS=(
    "OSError.*Address already in use"
    "Failed with result"
    "ERROR"
    "Exception"
    "Traceback"
    "CRITICAL"
)

# Gatewayログをチェック
check_gateway_log() {
    local log_file=$1
    local since_minutes=${2:-5}  # デフォルト5分前から
    
    if [ ! -f "$log_file" ]; then
        log "WARNING: Gateway log file not found: $log_file"
        return 0
    fi
    
    local errors=0
    local since_time=$(date -d "$since_minutes minutes ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -v-${since_minutes}M '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "")
    
    for pattern in "${ERROR_PATTERNS[@]}"; do
        local count=0
        if [ -n "$since_time" ]; then
            # タイムスタンプ以降のエラーを検索
            count=$(grep -i "$pattern" "$log_file" 2>/dev/null | awk -v since="$since_time" '$0 >= since' | wc -l)
        else
            # 最後の100行から検索
            count=$(tail -100 "$log_file" 2>/dev/null | grep -i "$pattern" | wc -l)
        fi
        
        if [ "$count" -gt 0 ]; then
            log "ERROR: Found $count occurrence(s) of pattern '$pattern' in Gateway log"
            errors=$((errors + count))
        fi
    done
    
    echo $errors
}

# Asteriskログをチェック
check_asterisk_log() {
    local log_file=$1
    local since_minutes=${2:-5}
    
    if [ ! -f "$log_file" ]; then
        log "WARNING: Asterisk log file not found: $log_file"
        return 0
    fi
    
    local errors=0
    local since_time=$(date -d "$since_minutes minutes ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -v-${since_minutes}M '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "")
    
    # Gateway関連のエラーを検索
    local patterns=(
        "ERROR.*gateway"
        "WARNING.*gateway"
        "CRITICAL.*gateway"
    )
    
    for pattern in "${patterns[@]}"; do
        local count=0
        if [ -n "$since_time" ]; then
            count=$(grep -i "$pattern" "$log_file" 2>/dev/null | awk -v since="$since_time" '$0 >= since' | wc -l)
        else
            count=$(tail -100 "$log_file" 2>/dev/null | grep -i "$pattern" | wc -l)
        fi
        
        if [ "$count" -gt 0 ]; then
            log "ERROR: Found $count occurrence(s) of pattern '$pattern' in Asterisk log"
            errors=$((errors + count))
        fi
    done
    
    echo $errors
}

# メイン処理
main() {
    log "=== Gateway Error Check Start ==="
    
    local gateway_errors=$(check_gateway_log "$GATEWAY_LOG" 5)
    local asterisk_errors=$(check_asterisk_log "$ASTERISK_LOG" 5)
    local total_errors=$((gateway_errors + asterisk_errors))
    
    log "Gateway log errors: $gateway_errors"
    log "Asterisk log errors: $asterisk_errors"
    log "Total errors: $total_errors"
    
    if [ "$total_errors" -gt 0 ]; then
        log "ALERT: $total_errors error(s) detected in logs"
        
        # メール通知（設定されている場合）
        if [ -n "$ALERT_EMAIL" ] && command -v mail >/dev/null 2>&1; then
            {
                echo "Gateway Error Alert"
                echo "Time: $(date)"
                echo "Gateway log errors: $gateway_errors"
                echo "Asterisk log errors: $asterisk_errors"
                echo "Total errors: $total_errors"
            } | mail -s "Gateway Error Alert" "$ALERT_EMAIL"
        fi
        
        return 1
    else
        log "OK: No errors detected in logs"
        return 0
    fi
}

main "$@"

