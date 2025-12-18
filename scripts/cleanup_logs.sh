#!/bin/bash
# ログクリーンアップスクリプト（再発防止用）

echo "=== ログクリーンアップ開始 ==="

# 1. event_listener.log をローテート（10MB以上の場合）
if [ -f /tmp/event_listener.log ] && [ $(stat -f%z /tmp/event_listener.log 2>/dev/null || stat -c%s /tmp/event_listener.log 2>/dev/null) -gt 10485760 ]; then
    mv /tmp/event_listener.log /tmp/event_listener.log.$(date +%Y%m%d_%H%M%S)
    echo "event_listener.log をローテートしました"
fi

# 2. 1日以上前のgatewayログを削除
find /tmp -name "gateway_*.log" -mtime +1 -delete
echo "1日以上前のgatewayログを削除しました"

# 3. FreeSWITCHコアダンプを削除
rm -f /var/lib/apport/coredump/core._usr_local_freeswitch_bin_freeswitch.*
echo "FreeSWITCHコアダンプファイルを削除しました"

# 4. ジャーナルログをクリーンアップ（2日より古いもの）
journalctl --vacuum-time=2d >/dev/null 2>&1
echo "ジャーナルログをクリーンアップしました"

echo "=== クリーンアップ完了 ==="
df -h / | tail -1

