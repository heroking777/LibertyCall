#!/bin/bash
# FreeSWITCH の通話開始を自動検出してRTPポート情報を取得する完全自動化スクリプト
# SIP INVITE を監視して、通話開始時に自動的にチャンネル情報とRTPポートを取得

# FreeSWITCH Event Socket Connection Parameters
HOST=127.0.0.1
PORT=8021
PASS=ClueCon

# ログファイル
LOG_DIR="/opt/libertycall/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/rtp_detection_$(date '+%Y%m%d_%H%M%S').log"

# ログ関数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== RTP Port Auto-Detection Script Started ==="
log "Log file: $LOG_FILE"

# FreeSWITCH Event Socket 接続確認
if ! fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "status" > /dev/null 2>&1; then
    log "[ERROR] FreeSWITCH Event Socket に接続できません"
    exit 1
fi

log "[INFO] FreeSWITCH Event Socket に接続しました"

# 前回のチャンネル数を記録
LAST_CHANNEL_COUNT=0

# 監視ループ
log "[INFO] チャンネル監視を開始します（Ctrl+Cで終了）"
while true; do
    # 現在のチャンネル数を取得
    CURRENT_CHANNELS=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "show channels" 2>/dev/null)
    CURRENT_COUNT=$(echo "$CURRENT_CHANNELS" | grep -E "^[0-9]+ total" | grep -oE "[0-9]+" | head -1)
    
    # チャンネル数が増えた場合（新しい通話開始）
    if [ -n "$CURRENT_COUNT" ] && [ "$CURRENT_COUNT" -gt "$LAST_CHANNEL_COUNT" ]; then
        log "[DETECTED] 新しい通話を検出しました（チャンネル数: $LAST_CHANNEL_COUNT -> $CURRENT_COUNT）"
        echo ""
        
        # 少し待ってから情報を取得（チャンネルが完全に確立されるまで）
        sleep 1
        
        # チャンネル情報を取得
        CHANNELS=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "show channels" 2>/dev/null)
        log "=== チャンネル情報 ==="
        echo "$CHANNELS" | tee -a "$LOG_FILE"
        echo ""
        
        # 最新のUUIDを取得（最初のアクティブなチャンネル）
        UUID=$(echo "$CHANNELS" | grep -v "^uuid," | grep -v "^$" | head -1 | cut -d',' -f1)
        
        if [ -n "$UUID" ] && [ "$UUID" != "uuid" ]; then
            log "[INFO] 検出されたUUID: $UUID"
            
            # RTPポート情報を取得
            sleep 0.5
            MEDIA_INFO=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "uuid_media $UUID" 2>/dev/null)
            
            if [ -n "$MEDIA_INFO" ]; then
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
                fi
            else
                log "[WARNING] uuid_media の実行結果が空です"
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

