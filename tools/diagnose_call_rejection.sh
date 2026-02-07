#!/bin/bash
# ポストモルテム解析スクリプト：即切断問題の自動診断
# Usage: ./diagnose_call_rejection.sh [phone_number]

PHONE_NUMBER="${1:-1633}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="/tmp/call_rejection_diagnosis_$(date +%Y%m%d_%H%M%S).log"

echo "=== CALL REJECTION DIAGNOSIS ===" | tee "$LOG_FILE"
echo "Timestamp: $TIMESTAMP" | tee -a "$LOG_FILE"
echo "Target Number: $PHONE_NUMBER" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "1. FreeSWITCH着信履歴と拒否理由の確認" | tee -a "$LOG_FILE"
echo "----------------------------------------" | tee -a "$LOG_FILE"

# FreeSWITCHログから該当番号の着信を検索
if [ -f "/var/log/freeswitch/freeswitch.log" ]; then
    echo "【FreeSWITCHログ】$PHONE_NUMBER に関する最新50件:" | tee -a "$LOG_FILE"
    grep "$PHONE_NUMBER" /var/log/freeswitch/freeswitch.log | tail -n 50 | tee -a "$LOG_FILE"
    
    echo "" | tee -a "$LOG_FILE"
    echo "【SIP応答コード】直近の拒否パターン:" | tee -a "$LOG_FILE"
    grep -E "(403|404|486|487|500|503)" /var/log/freeswitch/freeswitch.log | tail -n 10 | tee -a "$LOG_FILE"
    
    echo "" | tee -a "$LOG_FILE"
    echo "【Hangup Cause】切断理由の詳細:" | tee -a "$LOG_FILE"
    grep -i "hangup.*cause\|cause.*hangup" /var/log/freeswitch/freeswitch.log | tail -n 10 | tee -a "$LOG_FILE"
else
    echo "ERROR: FreeSWITCHログファイルが見つかりません: /var/log/freeswitch/freeswitch.log" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "2. Event Socketリスナー状態の確認" | tee -a "$LOG_FILE"
echo "----------------------------------------" | tee -a "$LOG_FILE"

# Event Socket (8021ポート) のリスナー状態
EVENT_SOCKET_STATUS=$(ss -tpln | grep 8021)
if [ -n "$EVENT_SOCKET_STATUS" ]; then
    echo "✅ Event Socket 8021ポートはリスニング中:" | tee -a "$LOG_FILE"
    echo "$EVENT_SOCKET_STATUS" | tee -a "$LOG_FILE"
else
    echo "❌ ERROR: Event Socket 8021ポートがリスニングされていません" | tee -a "$LOG_FILE"
    echo "   mod_event_socketが起動しているか確認してください" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "3. システムサービス状態の確認" | tee -a "$LOG_FILE"
echo "----------------------------------------" | tee -a "$LOG_FILE"

# LibertyCallサービス状態
echo "【LibertyCallサービス】:" | tee -a "$LOG_FILE"
systemctl status libertycall.service --no-pager --lines=5 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "【FreeSWITCHサービス】:" | tee -a "$LOG_FILE"
systemctl status freeswitch --no-pager --lines=5 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "4. RTPポート競合の確認" | tee -a "$LOG_FILE"
echo "----------------------------------------" | tee -a "$LOG_FILE"

# RTPポート7002の使用状況
RTP_STATUS=$(ss -ulpn | grep 7002)
if [ -n "$RTP_STATUS" ]; then
    echo "✅ RTP 7002ポートは使用中:" | tee -a "$LOG_FILE"
    echo "$RTP_STATUS" | tee -a "$LOG_FILE"
else
    echo "❌ RTP 7002ポートが未使用（Gatewayが起動していない可能性）" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "5. Gatewayプロセスの生存確認" | tee -a "$LOG_FILE"
echo "----------------------------------------" | tee -a "$LOG_FILE"

# Gateway関連プロセスの確認
echo "【Gateway関連プロセス】:" | tee -a "$LOG_FILE"
ps aux | grep -E "(gateway|realtime)" | grep -v grep | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "6. LUAスクリプトエラーの確認" | tee -a "$LOG_FILE"
echo "----------------------------------------" | tee -a "$LOG_FILE"

# LUAスクリプト関連のエラー検索
if [ -f "/var/log/freeswitch/freeswitch.log" ]; then
    echo "【LUAエラー】最新10件:" | tee -a "$LOG_FILE"
    grep -i "lua.*error\|play_audio_sequence" /var/log/freeswitch/freeswitch.log | tail -n 10 | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "=== DIAGNOSIS SUMMARY ===" | tee -a "$LOG_FILE"
echo "ログファイル: $LOG_FILE" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# 自動判定ロジック
echo "" | tee -a "$LOG_FILE"
echo "【自動判定】:" | tee -a "$LOG_FILE"

if [ -z "$EVENT_SOCKET_STATUS" ]; then
    echo "❌ 主要問題: Event Socketがダウンしています" | tee -a "$LOG_FILE"
    echo "   対策: sudo systemctl restart freeswitch" | tee -a "$LOG_FILE"
elif [ -z "$RTP_STATUS" ]; then
    echo "❌ 主要問題: Gatewayプロセスが起動していません" | tee -a "$LOG_FILE"
    echo "   対策: sudo systemctl restart libertycall.service" | tee -a "$LOG_FILE"
else
    echo "✅ 基本サービスは正常。詳細はFreeSWITCHログを確認してください" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "解析完了。詳細は $LOG_FILE を確認してください" | tee -a "$LOG_FILE"
