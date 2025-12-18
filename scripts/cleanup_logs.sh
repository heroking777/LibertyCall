#!/bin/bash
# ログクリーンアップスクリプト（再発防止用）

echo "=== ログクリーンアップ開始 ==="
echo "実行時刻: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. event_listener.log をローテート（10MB以上の場合）
if [ -f /tmp/event_listener.log ]; then
    SIZE=$(stat -c%s /tmp/event_listener.log 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 10485760 ]; then
        mv /tmp/event_listener.log /tmp/event_listener.log.$(date +%Y%m%d_%H%M%S)
        echo "✅ event_listener.log をローテートしました (${SIZE} bytes)"
    fi
fi

# 2. 1日以上前のgatewayログを削除
DELETED=$(find /tmp -name "gateway_*.log" -mtime +1 -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "✅ 1日以上前のgatewayログを削除しました (${DELETED} files)"
fi

# 3. FreeSWITCHコアダンプを削除
rm -f /var/lib/apport/coredump/core._usr_local_freeswitch_bin_freeswitch.*
echo "✅ FreeSWITCHコアダンプファイルを削除しました"

# 4. ジャーナルログをクリーンアップ（2日より古いもの）
journalctl --vacuum-time=2d >/dev/null 2>&1
echo "✅ ジャーナルログをクリーンアップしました"

# 5. pipキャッシュをクリーンアップ（1GB以上の場合）
if [ -d /root/.cache/pip ]; then
    PIP_SIZE=$(du -sm /root/.cache/pip 2>/dev/null | cut -f1)
    if [ "$PIP_SIZE" -gt 1024 ]; then
        rm -rf /root/.cache/pip/*
        echo "✅ pipキャッシュをクリーンアップしました (${PIP_SIZE}MB)"
    fi
fi

# 6. aptキャッシュをクリーンアップ
apt-get clean >/dev/null 2>&1
echo "✅ aptキャッシュをクリーンアップしました"

# 7. /var/crash をクリーンアップ
rm -rf /var/crash/*
echo "✅ クラッシュダンプをクリーンアップしました"

echo ""
echo "=== クリーンアップ完了 ==="
df -h / | tail -1

