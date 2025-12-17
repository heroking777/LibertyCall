#!/bin/bash
# FreeSWITCH の通話開始を自動検出してRTPポート情報を取得する改良版スクリプト
# 接続の安定化、エラーハンドリング、再接続機能を強化

# FreeSWITCH Event Socket Connection Parameters
HOST=127.0.0.1
PORT=8021
PASS=ClueCon

# 設定
MAX_RETRIES=5
RETRY_DELAY=2
CONNECTION_CHECK_INTERVAL=5

# ログファイル
LOG_DIR="/opt/libertycall/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/rtp_detection_$(date '+%Y%m%d_%H%M%S').log"

# ログ関数
log() {
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$message" | tee -a "$LOG_FILE"
}

log "=== RTP Port Auto-Detection Script (Enhanced) Started ==="
log "Log file: $LOG_FILE"
log "Event Socket: $HOST:$PORT"

# Event Socket接続確認関数（再接続機能付き）
check_event_socket() {
    local retry_count=0
    while [ $retry_count -lt $MAX_RETRIES ]; do
        if fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "status" > /dev/null 2>&1; then
            return 0
        fi
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log "[WARNING] Event Socket接続失敗 (試行 $retry_count/$MAX_RETRIES)、再接続を試みます..."
            sleep $RETRY_DELAY
        fi
    done
    log "[ERROR] Event Socket接続に失敗しました（$MAX_RETRIES回試行）"
    return 1
}

# 初期接続確認
if ! check_event_socket; then
    log "[ERROR] FreeSWITCH Event Socket に接続できません"
    log "確認: sudo netstat -tulnp | grep 8021"
    exit 1
fi

log "[SUCCESS] FreeSWITCH Event Socket に接続しました"

# チャンネル情報取得関数（再接続機能付き）
get_channels() {
    local retry_count=0
    local result=""
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        result=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "show channels" 2>/dev/null)
        
        if [ $? -eq 0 ] && [ -n "$result" ]; then
            echo "$result"
            return 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log "[WARNING] チャンネル情報取得失敗 (試行 $retry_count/$MAX_RETRIES)、再接続を試みます..."
            sleep $RETRY_DELAY
            check_event_socket || return 1
        fi
    done
    
    return 1
}

# RTP情報取得関数（再接続機能付き）
get_rtp_info() {
    local uuid=$1
    local retry_count=0
    local result=""
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        result=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "uuid_media $uuid" 2>/dev/null)
        
        if [ $? -eq 0 ] && [ -n "$result" ]; then
            echo "$result"
            return 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log "[WARNING] RTP情報取得失敗 (試行 $retry_count/$MAX_RETRIES)、再接続を試みます..."
            sleep $RETRY_DELAY
            check_event_socket || return 1
        fi
    done
    
    return 1
}

# 前回のチャンネル数を記録
LAST_CHANNEL_COUNT=0
CONNECTION_ERROR_COUNT=0

# 監視ループ
log "[INFO] チャンネル監視を開始します（Ctrl+Cで終了）"
log "[INFO] 接続チェック間隔: ${CONNECTION_CHECK_INTERVAL}秒"

while true; do
    # 定期的に接続を確認
    if [ $((CONNECTION_ERROR_COUNT % 10)) -eq 0 ]; then
        if ! check_event_socket; then
            CONNECTION_ERROR_COUNT=$((CONNECTION_ERROR_COUNT + 1))
            log "[ERROR] 接続エラーが継続しています（エラーカウント: $CONNECTION_ERROR_COUNT）"
            sleep $CONNECTION_CHECK_INTERVAL
            continue
        fi
        CONNECTION_ERROR_COUNT=0
    fi
    
    # 現在のチャンネル数を取得
    CURRENT_CHANNELS=$(get_channels)
    
    if [ $? -ne 0 ] || [ -z "$CURRENT_CHANNELS" ]; then
        CONNECTION_ERROR_COUNT=$((CONNECTION_ERROR_COUNT + 1))
        if [ $CONNECTION_ERROR_COUNT -ge 5 ]; then
            log "[ERROR] 接続エラーが続いています。再接続を試みます..."
            sleep $RETRY_DELAY
            check_event_socket
            CONNECTION_ERROR_COUNT=0
        fi
        sleep 1
        continue
    fi
    
    CURRENT_COUNT=$(echo "$CURRENT_CHANNELS" | grep -E "^[0-9]+ total" | grep -oE "[0-9]+" | head -1)
    
    # チャンネル数が増えた場合（新しい通話開始）
    if [ -n "$CURRENT_COUNT" ] && [ "$CURRENT_COUNT" -gt "$LAST_CHANNEL_COUNT" ]; then
        log "[DETECTED] 新しい通話を検出しました（チャンネル数: $LAST_CHANNEL_COUNT -> $CURRENT_COUNT）"
        echo ""
        
        # 少し待ってから情報を取得（チャンネルが完全に確立されるまで）
        sleep 1.5
        
        # チャンネル情報を取得
        CHANNELS=$(get_channels)
        
        if [ $? -eq 0 ] && [ -n "$CHANNELS" ]; then
            log "=== チャンネル情報 ==="
            echo "$CHANNELS" | tee -a "$LOG_FILE"
            echo ""
            
            # 最新のUUIDを取得（最初のアクティブなチャンネル）
            UUID=$(echo "$CHANNELS" | grep -v "^uuid," | grep -v "^$" | head -1 | cut -d',' -f1)
            
            if [ -n "$UUID" ] && [ "$UUID" != "uuid" ]; then
                log "[INFO] 検出されたUUID: $UUID"
                
                # RTPポート情報を取得
                sleep 0.5
                MEDIA_INFO=$(get_rtp_info "$UUID")
                
                if [ $? -eq 0 ] && [ -n "$MEDIA_INFO" ]; then
                    log "=== RTPポート情報 ==="
                    echo "$MEDIA_INFO" | tee -a "$LOG_FILE"
                    echo ""
                    
                    # RTP情報を抽出
                    RTP_PORT=$(echo "$MEDIA_INFO" | grep -i "RTP Local Port" | grep -oE "[0-9]+" | head -1)
                    RTP_REMOTE_IP=$(echo "$MEDIA_INFO" | grep -i "RTP Remote IP" | grep -oE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | head -1)
                    RTP_REMOTE_PORT=$(echo "$MEDIA_INFO" | grep -i "RTP Remote Port" | grep -oE "[0-9]+" | head -1)
                    
                    if [ -n "$RTP_PORT" ]; then
                        log "[SUCCESS] RTP情報を取得しました"
                        log "RTP Local Port: $RTP_PORT"
                        [ -n "$RTP_REMOTE_IP" ] && log "RTP Remote IP: $RTP_REMOTE_IP"
                        [ -n "$RTP_REMOTE_PORT" ] && log "RTP Remote Port: $RTP_REMOTE_PORT"
                        log "tcpdump コマンド: sudo tcpdump -n -i any udp port $RTP_PORT -vvv -c 20"
                        echo ""
                    else
                        log "[WARNING] RTPポート情報が見つかりませんでした"
                        log "[INFO] RTPネゴシエーションが完了するまで待機中..."
                    fi
                else
                    log "[WARNING] uuid_media の実行結果が空です"
                fi
            fi
        fi
        
        LAST_CHANNEL_COUNT=$CURRENT_COUNT
    elif [ -n "$CURRENT_COUNT" ] && [ "$CURRENT_COUNT" -lt "$LAST_CHANNEL_COUNT" ]; then
        # チャンネル数が減った場合（通話終了）
        log "[INFO] 通話が終了しました（チャンネル数: $LAST_CHANNEL_COUNT -> $CURRENT_COUNT）"
        LAST_CHANNEL_COUNT=$CURRENT_COUNT
    fi
    
    # 1秒ごとに監視
    sleep 1
done

