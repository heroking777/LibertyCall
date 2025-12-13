#!/bin/bash
# AUTO-HANGUP デバッグ用スクリプト
# 次回通話時に実行して、hangupが実際に効いているか確認する

echo "=== チャネル一覧 ==="
asterisk -rx "core show channels verbose"
echo ""
echo "=== Asteriskログ（直近200行、Hangup関連） ==="
tail -n 200 /var/log/asterisk/full.log | grep -E "Hangup|requested hangup|UnicastRTP|PJSIP/" | tail -20
echo ""
echo "=== Gatewayログ（AUTO-HANGUP関連） ==="
grep -E "AUTO-HANGUP|SILENCE DETECTED" /opt/libertycall/logs/systemd_gateway_stdout.log | tail -10
echo ""
echo "=== hangup_call.pyログ（直近20行） ==="
tail -n 20 /opt/libertycall/logs/hangup_call.log
echo ""
echo "=== 完了 ==="

