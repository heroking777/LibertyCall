#!/bin/bash
# -*- coding: utf-8 -*-
set -e

# 転送失敗時のログを会話ログに追加するスクリプト
# 引数: call_id, dialstatus, hangupcause

CALL_ID="$1"
DIALSTATUS="$2"
HANGUPCAUSE="$3"

# 引数無いときはUNIQUEIDベースのcall_idを生成
if [ -z "$CALL_ID" ]; then
    # AsteriskのUNIQUEIDを使用（フォールバック）
    CALL_ID="000-$(date +%Y%m%d%H%M%S)"
fi

# ログディレクトリのパス（既存のログパスに合わせる）
LOG_BASE="/opt/libertycall/logs/calls/000"
LOG_FILE="${LOG_BASE}/${CALL_ID}.log"

# ディレクトリがなければ作成
mkdir -p "${LOG_BASE}"

# タイムスタンプ関数
timestamp() {
    date +"%Y-%m-%d %H:%M:%S"
}

# AI応答テキスト
AI_TEXT="現在、担当者の回線が込み合っております。こちらから折り返しご連絡いたしますので、このまま続けてお名前とご連絡先をお話しください。お話しが終わりましたら、そのまま電話をお切りください。"

# ログ行を追加（UTF-8で保存）
# フォーマット: [timestamp] [-] ROLE (optional_info) text
{
    echo "[$(timestamp)] [-] SYSTEM [HANDOFF_FAIL] DIALSTATUS=${DIALSTATUS} HANGUPCAUSE=${HANGUPCAUSE}"
    echo "[$(timestamp)] [-] AI (handoff_fail) ${AI_TEXT}"
} >> "${LOG_FILE}"

# Gateway経由でTTSアナウンスを送信
# 注意: 現在の実装では、RTP経由で直接送信する方法を使用
# 将来的には、GatewayのAPIを使用する方法に置き換える
/opt/libertycall/venv/bin/python /opt/libertycall/scripts/handoff_fail_tts.py "${CALL_ID}" || true

# 正常終了
exit 0

