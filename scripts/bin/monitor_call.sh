#!/bin/bash
# 通話監視スクリプト - リアルタイムでログを監視

echo "=== 通話監視開始 ==="
echo "新しい通話を開始してください..."
echo ""

# バックグラウンドでFreeSWITCHログを監視
(
  sudo tail -f /usr/local/freeswitch/log/freeswitch.log 2>/dev/null | grep --line-buffered -E "INVITE|180|200|BYE|rtp_stream|7003|PCMU|SDP|a=rtpmap" | while read line; do
    echo "[FS] $(date '+%H:%M:%S') $line"
  done
) &
FS_PID=$!

# バックグラウンドでLibertyCallログを監視
(
  sudo journalctl -u libertycall -f --no-pager 2>/dev/null | grep --line-buffered -E "RTP_RECV|TTS_QUEUE|7003|ERROR|WARNING" | while read line; do
    echo "[LC] $(date '+%H:%M:%S') $line"
  done
) &
LC_PID=$!

# 定期的にチャネル状態を確認
(
  while true; do
    sleep 2
    channels=$(fs_cli -x "show channels" 2>/dev/null | grep -c "total")
    if [ "$channels" != "0" ]; then
      echo ""
      echo "=== チャネル状態 ==="
      fs_cli -x "show channels" 2>/dev/null | grep -E "read_codec|write_codec|7003|state"
      echo ""
    fi
  done
) &
CH_PID=$!

# クリーンアップ関数
cleanup() {
  echo ""
  echo "監視を停止します..."
  kill $FS_PID $LC_PID $CH_PID 2>/dev/null
  exit 0
}

trap cleanup SIGINT SIGTERM

# メインループ
echo "監視中... (Ctrl+Cで停止)"
wait

