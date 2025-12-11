#!/bin/bash
# -*- coding: utf-8 -*-
# Gatewayポート競合監視スクリプト
# ポート7100の使用状況を確認し、複数のプロセスが起動していないかチェック

set -e

PORT=7100
LOG_FILE="/opt/libertycall/logs/gateway_port_check.log"
ALERT_EMAIL="${GATEWAY_ALERT_EMAIL:-}"  # 環境変数で設定可能

# ログディレクトリを作成
mkdir -p "$(dirname "$LOG_FILE")"

# ログ関数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ポート使用状況を確認
check_port() {
    local port=$1
    local processes=$(sudo lsof -i :$port 2>/dev/null | grep -v COMMAND | wc -l)
    echo $processes
}

# Gatewayプロセス数を確認（tailコマンドを除外）
check_gateway_processes() {
    local count=$(ps aux | grep -E "realtime_gateway|gateway\.py" | grep -v grep | grep -v "tail" | wc -l)
    echo $count
}

# メイン処理
main() {
    log "=== Gateway Port Check Start ==="
    
    # ポート7100の使用状況
    local port_users=$(check_port $PORT)
    log "Port $PORT users: $port_users"
    
    # Gatewayプロセス数
    local gateway_count=$(check_gateway_processes)
    log "Gateway processes: $gateway_count"
    
    # 問題検出
    local issues=0
    
    # ポートが複数のプロセスで使用されている
    if [ "$port_users" -gt 1 ]; then
        log "WARNING: Port $PORT is used by $port_users processes"
        issues=$((issues + 1))
    fi
    
    # Gatewayプロセスが複数起動している
    if [ "$gateway_count" -gt 1 ]; then
        log "WARNING: $gateway_count Gateway processes are running (expected: 1)"
        issues=$((issues + 1))
    fi
    
    # Gatewayプロセスが起動していない
    if [ "$gateway_count" -eq 0 ]; then
        log "ERROR: No Gateway processes are running"
        issues=$((issues + 1))
    fi
    
    # systemdサービスの状態確認
    if systemctl is-active --quiet gateway.service; then
        log "Gateway service: active"
    else
        log "ERROR: Gateway service is not active"
        issues=$((issues + 1))
    fi
    
    # 問題がある場合は通知
    if [ "$issues" -gt 0 ]; then
        log "ALERT: $issues issue(s) detected"
        
        # メール通知（設定されている場合）
        if [ -n "$ALERT_EMAIL" ] && command -v mail >/dev/null 2>&1; then
            {
                echo "Gateway Port Conflict Alert"
                echo "Time: $(date)"
                echo "Port $PORT users: $port_users"
                echo "Gateway processes: $gateway_count"
                echo "Service status: $(systemctl is-active gateway.service || echo 'inactive')"
            } | mail -s "Gateway Port Conflict Alert" "$ALERT_EMAIL"
        fi
        
        return 1
    else
        log "OK: No issues detected"
        return 0
    fi
}

main "$@"

