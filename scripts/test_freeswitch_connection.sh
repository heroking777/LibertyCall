#!/bin/bash
# FreeSWITCH接続確認スクリプト

echo "=========================================="
echo "FreeSWITCH接続確認"
echo "=========================================="

echo ""
echo "1. FreeSWITCHステータス確認"
echo "----------------------------------------"
sudo fs_cli -x "status" 2>&1 | head -20

echo ""
echo "2. Sofia SIPステータス確認"
echo "----------------------------------------"
sudo fs_cli -x "sofia status" 2>&1 | head -30

echo ""
echo "3. ESLポート確認"
echo "----------------------------------------"
sudo netstat -tulnp | grep 8021 || echo "⚠️  ポート8021が見つかりません"

echo ""
echo "4. FreeSWITCHプロセス確認"
echo "----------------------------------------"
ps aux | grep freeswitch | grep -v grep || echo "⚠️  FreeSWITCHプロセスが見つかりません"

echo ""
echo "=========================================="
echo "確認完了"
echo "=========================================="

