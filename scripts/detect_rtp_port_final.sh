#!/bin/bash
# FreeSWITCH Event Socket 経由で通話中のチャンネル情報とRTPポートを取得する最終版スクリプト
# 接続待ちループ + 再接続対応 + セッション維持で確実に動作

# FreeSWITCH Event Socket Connection Parameters
HOST=127.0.0.1
PORT=8021
PASS=ClueCon

# 設定
MAX_WAIT_TIME=30  # 最大待機時間（秒）
WAIT_INTERVAL=1   # 待機間隔（秒）

# タイムスタンプ
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "=== RTP Port Detection Script (Final) - $TIMESTAMP ==="
echo ""

# ステップ1: Event Socket接続待ちループ（最重要）
echo "[STEP 1] Event Socket接続待機中..."
WAIT_COUNT=0
until fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "status" > /dev/null 2>&1; do
    WAIT_COUNT=$((WAIT_COUNT + 1))
    if [ $WAIT_COUNT -ge $MAX_WAIT_TIME ]; then
        echo "[ERROR] Event Socket接続待機がタイムアウトしました（${MAX_WAIT_TIME}秒）"
        echo ""
        echo "確認手順:"
        echo "  1. FreeSWITCHが起動しているか: sudo systemctl status freeswitch"
        echo "  2. ポート8021がLISTENしているか: sudo netstat -tulnp | grep 8021"
        echo "  3. Event Socket設定を確認: cat /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml"
        exit 1
    fi
    if [ $((WAIT_COUNT % 5)) -eq 0 ]; then
        echo "  [INFO] 接続待機中... (${WAIT_COUNT}/${MAX_WAIT_TIME}秒)"
    fi
    sleep $WAIT_INTERVAL
done

echo "[SUCCESS] Event Socket接続を確認しました"
echo ""

# ステップ2: チャンネル情報取得（接続を保持して連続コマンド実行）
echo "[STEP 2] チャンネル情報取得中..."

# 接続を保持して複数コマンドを連続実行
CHANNEL_OUTPUT=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" <<EOF 2>/dev/null
show channels
sleep 0.5
show channels
EOF
)

if [ $? -ne 0 ] || [ -z "$CHANNEL_OUTPUT" ]; then
    echo "[ERROR] チャンネル情報の取得に失敗しました"
    echo "再接続を試みます..."
    
    # 再接続モードで再試行
    CHANNEL_OUTPUT=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -r <<EOF 2>/dev/null
show channels
EOF
)
    
    if [ $? -ne 0 ] || [ -z "$CHANNEL_OUTPUT" ]; then
        echo "[ERROR] 再接続後もチャンネル情報の取得に失敗しました"
        exit 1
    fi
fi

# アクティブなチャンネルがあるか確認
if ! echo "$CHANNEL_OUTPUT" | grep -q "total.*[1-9]"; then
    echo "[INFO] アクティブなチャンネルが見つかりませんでした"
    echo "通話が開始されていることを確認してください"
    exit 0
fi

echo "[SUCCESS] アクティブなチャンネルを検出しました"
echo ""
echo "=== チャンネル情報 ==="
echo "$CHANNEL_OUTPUT"
echo ""

# UUIDを抽出
UUID=$(echo "$CHANNEL_OUTPUT" | grep -v "^uuid," | grep -v "^$" | head -1 | cut -d',' -f1)

if [ -z "$UUID" ] || [ "$UUID" = "uuid" ]; then
    echo "[WARNING] 有効なUUIDが見つかりませんでした"
    exit 1
fi

echo "[INFO] 検出されたUUID: $UUID"
echo ""

# ステップ3: RTPポート情報取得（接続を保持して連続コマンド実行）
echo "[STEP 3] RTPポート情報取得中..."

# 少し待ってからRTP情報を取得（RTPネゴシエーションが完了するまで）
sleep 1

# 接続を保持してRTP情報を取得
MEDIA_OUTPUT=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" <<EOF 2>/dev/null
uuid_media $UUID
EOF
)

if [ $? -ne 0 ] || [ -z "$MEDIA_OUTPUT" ]; then
    echo "[WARNING] RTP情報の取得に失敗しました。再接続を試みます..."
    
    # 再接続モードで再試行
    MEDIA_OUTPUT=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -r <<EOF 2>/dev/null
uuid_media $UUID
EOF
)
    
    if [ $? -ne 0 ] || [ -z "$MEDIA_OUTPUT" ]; then
        echo "[ERROR] 再接続後もRTP情報の取得に失敗しました"
        echo "[INFO] RTPネゴシエーションが完了していない可能性があります"
        echo "1-2秒待ってから再度実行してください"
        exit 1
    fi
fi

echo "$MEDIA_OUTPUT"
echo ""

# RTP情報を抽出
RTP_PORT=$(echo "$MEDIA_OUTPUT" | grep -i "RTP Local Port" | grep -oE "[0-9]+" | head -1)
RTP_REMOTE_IP=$(echo "$MEDIA_OUTPUT" | grep -i "RTP Remote IP" | grep -oE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | head -1)
RTP_REMOTE_PORT=$(echo "$MEDIA_OUTPUT" | grep -i "RTP Remote Port" | grep -oE "[0-9]+" | head -1)

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

