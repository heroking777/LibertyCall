#!/bin/bash
# FreeSWITCH Event Socket接続確認用ワンライナーコマンド集

HOST=127.0.0.1
PORT=8021
PASS=ClueCon

echo "=== FreeSWITCH Event Socket 接続確認 ==="
echo ""

# 1. ポート8021のLISTEN状態確認
echo "[1] ポート8021のLISTEN状態確認:"
sudo netstat -tulnp | grep 8021 || echo "  [ERROR] ポート8021がLISTENしていません"
echo ""

# 2. Event Socket設定確認
echo "[2] Event Socket設定確認:"
echo "  listen-ip: $(grep 'listen-ip' /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml | grep -oE 'value="[^"]*"' | cut -d'"' -f2)"
echo "  listen-port: $(grep 'listen-port' /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml | grep -oE 'value="[^"]*"' | cut -d'"' -f2)"
echo ""

# 3. fs_cli接続テスト（再接続モード）
echo "[3] fs_cli接続テスト（再接続モード）:"
if fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -r -x "status" > /dev/null 2>&1; then
    echo "  [SUCCESS] 接続成功"
    fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -r -x "status" 2>&1 | head -3
else
    echo "  [ERROR] 接続失敗"
    echo "  エラー詳細:"
    fs_cli -H "$HOST" -P "$PORT" -p "$PASS" -r -x "status" 2>&1
fi
echo ""

# 4. FreeSWITCHプロセス確認
echo "[4] FreeSWITCHプロセス確認:"
if ps aux | grep -v grep | grep -q freeswitch; then
    echo "  [SUCCESS] FreeSWITCHプロセスが稼働中"
    ps aux | grep -v grep | grep freeswitch | head -1
else
    echo "  [ERROR] FreeSWITCHプロセスが見つかりません"
fi
echo ""

# 5. Event Socketログ確認
echo "[5] Event Socket起動ログ確認:"
if sudo tail -200 /usr/local/freeswitch/log/freeswitch.log | grep -qi "Socket up listening\|event_socket"; then
    echo "  [SUCCESS] Event Socket起動ログを確認"
    sudo tail -200 /usr/local/freeswitch/log/freeswitch.log | grep -i "Socket up listening\|event_socket" | tail -1
else
    echo "  [WARNING] Event Socket起動ログが見つかりません"
fi
echo ""

echo "=== 確認完了 ==="

