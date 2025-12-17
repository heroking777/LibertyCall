#!/bin/bash
# FreeSWITCH Event Socket 経由で通話中のチャンネル情報とRTPポートを取得するスクリプト
# 通話が短時間で切れても、一発で情報を取得できる

# FreeSWITCH Event Socket Connection Parameters
HOST=127.0.0.1
PORT=8021
PASS=ClueCon

# タイムスタンプ
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "=== RTP Port Detection Script - $TIMESTAMP ==="
echo ""

# 接続確認
if ! fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "status" > /dev/null 2>&1; then
    echo "[ERROR] FreeSWITCH Event Socket に接続できません"
    echo "確認: sudo netstat -tulnp | grep 8021"
    exit 1
fi

echo "[INFO] FreeSWITCH Event Socket に接続しました"
echo ""

# show channels を複数回実行（通話が短い場合でも確実に取得）
echo "=== チャンネル情報取得中 ==="
for i in {1..3}; do
    echo "[試行 $i/3] show channels 実行中..."
    CHANNELS=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "show channels" 2>/dev/null)
    
    # アクティブなチャンネルがあるか確認
    if echo "$CHANNELS" | grep -q "total.*[1-9]"; then
        echo "[SUCCESS] アクティブなチャンネルを検出しました"
        echo ""
        echo "=== チャンネル情報 ==="
        echo "$CHANNELS"
        echo ""
        
        # UUIDを抽出
        UUID=$(echo "$CHANNELS" | grep -v "^uuid," | grep -v "^$" | head -1 | cut -d',' -f1)
        
        if [ -n "$UUID" ] && [ "$UUID" != "uuid" ]; then
            echo "[INFO] 検出されたUUID: $UUID"
            echo ""
            
            # uuid_media でRTPポート情報を取得
            echo "=== RTPポート情報取得中 ==="
            MEDIA_INFO=$(fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -x "uuid_media $UUID" 2>/dev/null)
            
            if [ -n "$MEDIA_INFO" ]; then
                echo "$MEDIA_INFO"
                echo ""
                
                # RTP Local Portを抽出
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
                else
                    echo "[WARNING] RTPポート情報が見つかりませんでした"
                fi
            else
                echo "[WARNING] uuid_media の実行結果が空です"
            fi
        else
            echo "[WARNING] 有効なUUIDが見つかりませんでした"
        fi
        
        exit 0
    fi
    
    if [ $i -lt 3 ]; then
        sleep 0.5
    fi
done

echo "[INFO] アクティブなチャンネルが見つかりませんでした"
echo "通話が開始されていることを確認してください"
exit 0

