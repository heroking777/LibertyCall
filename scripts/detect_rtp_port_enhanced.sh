#!/bin/bash
# FreeSWITCH Event Socket 経由で通話中のチャンネル情報とRTPポートを取得する改良版スクリプト
# 接続の安定化、エラーハンドリング、再接続機能を強化

# FreeSWITCH Event Socket Connection Parameters
HOST=127.0.0.1
PORT=8021
PASS=ClueCon

# 設定
MAX_RETRIES=5
RETRY_DELAY=1
CONNECTION_TIMEOUT=10

# タイムスタンプ
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "=== RTP Port Detection Script (Enhanced) - $TIMESTAMP ==="
echo ""

# Event Socket接続確認関数
check_event_socket() {
    local retry_count=0
    while [ $retry_count -lt $MAX_RETRIES ]; do
        if fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "status" > /dev/null 2>&1; then
            return 0
        fi
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            echo "[WARNING] Event Socket接続失敗 (試行 $retry_count/$MAX_RETRIES)、再接続を試みます..."
            sleep $RETRY_DELAY
        fi
    done
    return 1
}

# 接続確認（再接続機能付き）
if ! check_event_socket; then
    echo "[ERROR] FreeSWITCH Event Socket に接続できません（$MAX_RETRIES回試行）"
    echo ""
    echo "確認手順:"
    echo "  1. FreeSWITCHが起動しているか: sudo systemctl status freeswitch"
    echo "  2. ポート8021がLISTENしているか: sudo netstat -tulnp | grep 8021"
    echo "  3. Event Socket設定を確認: cat /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml"
    exit 1
fi

echo "[SUCCESS] FreeSWITCH Event Socket に接続しました"
echo ""

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
            echo "[WARNING] チャンネル情報取得失敗 (試行 $retry_count/$MAX_RETRIES)、再接続を試みます..."
            sleep $RETRY_DELAY
            # 接続を再確認
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
            echo "[WARNING] RTP情報取得失敗 (試行 $retry_count/$MAX_RETRIES)、再接続を試みます..."
            sleep $RETRY_DELAY
            # 接続を再確認
            check_event_socket || return 1
        fi
    done
    
    return 1
}

# チャンネル情報取得（複数回試行）
echo "=== チャンネル情報取得中 ==="
CHANNELS=""
for i in {1..3}; do
    echo "[試行 $i/3] show channels 実行中..."
    CHANNELS=$(get_channels)
    
    if [ $? -eq 0 ] && [ -n "$CHANNELS" ]; then
        # アクティブなチャンネルがあるか確認
        if echo "$CHANNELS" | grep -q "total.*[1-9]"; then
            echo "[SUCCESS] アクティブなチャンネルを検出しました"
            echo ""
            echo "=== チャンネル情報 ==="
            echo "$CHANNELS"
            echo ""
            break
        fi
    fi
    
    if [ $i -lt 3 ]; then
        sleep 0.5
    fi
done

# アクティブなチャンネルがない場合
if [ -z "$CHANNELS" ] || ! echo "$CHANNELS" | grep -q "total.*[1-9]"; then
    echo "[INFO] アクティブなチャンネルが見つかりませんでした"
    echo "通話が開始されていることを確認してください"
    exit 0
fi

# UUIDを抽出
UUID=$(echo "$CHANNELS" | grep -v "^uuid," | grep -v "^$" | head -1 | cut -d',' -f1)

if [ -z "$UUID" ] || [ "$UUID" = "uuid" ]; then
    echo "[WARNING] 有効なUUIDが見つかりませんでした"
    exit 1
fi

echo "[INFO] 検出されたUUID: $UUID"
echo ""

# RTPポート情報を取得
echo "=== RTPポート情報取得中 ==="
MEDIA_INFO=$(get_rtp_info "$UUID")

if [ $? -ne 0 ] || [ -z "$MEDIA_INFO" ]; then
    echo "[ERROR] RTP情報の取得に失敗しました"
    exit 1
fi

echo "$MEDIA_INFO"
echo ""

# RTP情報を抽出
RTP_PORT=$(echo "$MEDIA_INFO" | grep -i "RTP Local Port" | grep -oE "[0-9]+" | head -1)
RTP_REMOTE_IP=$(echo "$MEDIA_INFO" | grep -i "RTP Remote IP" | grep -oE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | head -1)
RTP_REMOTE_PORT=$(echo "$MEDIA_INFO" | grep -i "RTP Remote Port" | grep -oE "[0-9]+" | head -1)

if [ -n "$RTP_PORT" ]; then
    echo "=== 抽出されたRTP情報 ==="
    echo "RTP Local Port: $RTP_PORT"
    [ -n "$RTP_REMOTE_IP" ] && echo "RTP Remote IP: $RTP_REMOTE_IP"
    [ -n "$RTP_REMOTE_PORT" ] && echo "RTP Remote Port: $RTP_REMOTE_PORT"
    echo ""
    echo "=== tcpdump コマンド例 ==="
    echo "sudo tcpdump -n -i any udp port $RTP_PORT -vvv -c 20"
    echo ""
    echo "=== 双方向RTP確認コマンド ==="
    echo "# FreeSWITCH → Rakuten の送信を確認"
    echo "sudo tcpdump -n -i any 'udp port $RTP_PORT and src host 160.251.170.253' -vvv -c 20"
    echo ""
    echo "# Rakuten → FreeSWITCH の受信を確認"
    echo "sudo tcpdump -n -i any 'udp port $RTP_PORT and dst host 160.251.170.253' -vvv -c 20"
    echo ""
    exit 0
else
    echo "[WARNING] RTPポート情報が見つかりませんでした"
    echo "RTPネゴシエーションが完了していない可能性があります"
    echo "1-2秒待ってから再度実行してください"
    exit 1
fi

