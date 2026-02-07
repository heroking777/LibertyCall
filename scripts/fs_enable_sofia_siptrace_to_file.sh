#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - sofia siptrace を「SIP本体が取れる形」でファイルへ出す導通を作る。
#  - 通話は不要。まず設定と"ファイル生成される状態"を作ってスタンバイ報告する。
#
# 使い方:
#   ./fs_enable_sofia_siptrace_to_file.sh [profile]
#   例: ./fs_enable_sofia_siptrace_to_file.sh lab_open

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

PROFILE="${1:-lab_open}"
LOGDIR="/usr/local/freeswitch/log"
OUT="/tmp/fs_enable_sofia_siptrace_$(date +%s).txt"

run_fs(){ timeout 8s ${FSCLI} -x "$1" 2>/dev/null || true; }

echo "[prep] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo

  echo "== profile =="
  echo "${PROFILE}"
  echo

  echo "== sofia status (profile visibility) =="
  run_fs "sofia status" | head -n 120 || true
  echo

  echo "== enable siptrace (global) =="
  run_fs "sofia global siptrace on" || true
  echo

  echo "== enable siptrace (profile) =="
  run_fs "sofia profile ${PROFILE} siptrace on" || true
  echo

  echo "== logdir candidates (top 50) =="
  timeout 10s ls -lt "${LOGDIR}" | head -n 50 || true
  echo

  echo "== search siptrace-like files in logdir =="
  timeout 10s ls -1 "${LOGDIR}" 2>/dev/null | egrep -i "siptrace|sofia.*trace|sofia.*sip" || true
  echo

  echo "== quick grep for SIP start-lines inside freeswitch.log.1 (last 80) =="
  # ここで "INVITE sip:" 等が全く無いなら、やはり専用ファイル化が必要
  timeout 12s egrep -ain "^(INVITE|ACK|BYE|CANCEL|REGISTER|SIP/2\.0)" "${LOGDIR}/freeswitch.log.1" 2>/dev/null | tail -n 80 || true
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
