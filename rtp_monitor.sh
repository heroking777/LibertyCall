#!/bin/bash
# RTPパケット監視スクリプト
# 通話中にRakutenから来るRTPパケットをリアルタイム検出して記録

LOG_DIR="/tmp/rtp_monitor"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/rtp_monitor_${TIMESTAMP}.log"

echo "==========================================" | tee -a "$LOG_FILE"
echo "RTPパケット監視開始: $(date)" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Step 1: FreeSWITCHが開いているRTPポートを確認
echo "[Step 1] FreeSWITCHが開いているRTPポート:" | tee -a "$LOG_FILE"
sudo ss -lunp | grep freeswitch | grep -E ":[0-9]{4,5}" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Step 2: 最新のAUDIO RTP設定を確認
echo "[Step 2] 最新のAUDIO RTP設定:" | tee -a "$LOG_FILE"
sudo grep -E "AUDIO RTP" /usr/local/freeswitch/log/freeswitch.log | tail -n 1 | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Step 3: Rakuten側からのUDPパケットを監視（バックグラウンド）
echo "[Step 3] Rakuten側からのUDPパケット監視開始..." | tee -a "$LOG_FILE"
echo "監視中... (Ctrl+Cで停止)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# tcpdumpでRakutenからのUDPパケットをキャプチャ
sudo tcpdump -n -i any src net 61.213.230.0/24 and udp -vvv 2>&1 | \
    while IFS= read -r line; do
        echo "[$(date +%H:%M:%S)] $line" | tee -a "$LOG_FILE"
        
        # ポート番号を抽出して表示
        if echo "$line" | grep -q "\.\([0-9]\{4,5\}\) >"; then
            PORT=$(echo "$line" | grep -oP "\.\K[0-9]{4,5}(?= >)" | head -1)
            if [ ! -z "$PORT" ]; then
                echo "  → 検出ポート: $PORT" | tee -a "$LOG_FILE"
            fi
        fi
    done

echo "" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "監視終了: $(date)" | tee -a "$LOG_FILE"
echo "ログファイル: $LOG_FILE" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"

