#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - freeswitch.log にCALL-IDが出ない環境でもSIP/SDPを確実に取るため、
#    sofia siptrace を短時間だけONにして通話後にログを回収する（リアルタイム監視は禁止）。
#  - 長時間ONはログ肥大化するので禁止。burst運用のみ。
#
# 使い方:
#   # 1) 通話前に一度だけ実行してON準備（すぐ戻す）
#   ./fs_sofia_siptrace_burst.sh prep
#   # 2) 通話後に回収（UUIDまたはCALL-IDを任意で渡すとgrepも同梱）
#   ./fs_sofia_siptrace_burst.sh collect <UUID_or_CALLID_optional>

MODE="${1:-}"
KEY="${2:-}"

FSCLI="fs_cli"
LOGDIR="/usr/local/freeswitch/log"
OUT="/tmp/fs_sofia_siptrace_${MODE}_$(date +%s).txt"

if [[ -z "${MODE}" ]]; then
  echo "usage: $0 prep|collect [UUID_or_CALLID]" >&2
  exit 1
fi

if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

run_fs() { timeout 8s ${FSCLI} -x "$1" 2>/dev/null || true; }

echo "[siptrace] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo
  echo "== mode =="
  echo "${MODE}"
  echo

  echo "== sofia status (head) =="
  run_fs "sofia status" | head -n 120 || true
  echo

  if [[ "${MODE}" == "prep" ]]; then
    echo "== enable siptrace (global) =="
    # burst準備：ONにしてすぐOFFに戻すのではなく、管理者が通話直前に再度prepしてもOK
    run_fs "sofia global siptrace on"
    echo
    echo "== verify siptrace flag (status again head) =="
    run_fs "sofia status" | head -n 120 || true
    echo
    echo "NOTE: siptrace is ON now. After your test call, run 'collect' to save logs, then we will turn it OFF."
    echo
  elif [[ "${MODE}" == "collect" ]]; then
    echo "== list logdir =="
    timeout 6s ls -lt "${LOGDIR}" | head -n 60 || true
    echo

    echo "== find siptrace-like files (top) =="
    timeout 10s bash -lc "ls -1 ${LOGDIR} | egrep -i 'siptrace|sofia.*sip|sofia.*trace' | tail -n 60" || true
    echo

    echo "== tail freeswitch.log head signals (optional) =="
    timeout 6s tail -n 120 "${LOGDIR}/freeswitch.log" 2>/dev/null || true
    echo

    if [[ -n "${KEY}" ]]; then
      echo "== grep KEY in logdir (KEY=${KEY}) =="
      timeout 12s bash -lc "grep -RIn --line-buffered -F \"${KEY}\" \"${LOGDIR}\" 2>/dev/null | tail -n 120" || true
      echo
    fi

    echo "== disable siptrace (global) =="
    run_fs "sofia global siptrace off"
    echo
    echo "== verify siptrace flag (status again head) =="
    run_fs "sofia status" | head -n 120 || true
    echo
  else
    echo "[error] unknown mode: ${MODE}"
    exit 1
  fi
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
