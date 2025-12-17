#!/bin/bash
# Event Socket Listener を起動するスクリプト

cd /opt/libertycall

# 既存のプロセスを停止
pkill -f gateway_event_listener.py 2>/dev/null
sleep 1

# Event Socket Listener を起動
nohup python3 gateway_event_listener.py >> /opt/libertycall/logs/event_listener.log 2>&1 &

echo "Event Socket Listener を起動しました"
echo "ログファイル: /opt/libertycall/logs/event_listener.log"
echo ""
echo "ログを確認: tail -f /opt/libertycall/logs/event_listener.log"

