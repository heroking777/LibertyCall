#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - この環境では sofia siptrace が専用ファイルに出ない可能性があるため、
#    freeswitch.log から指定CALL-IDに関係する行とその前後文脈をオフライン抽出する。
#
# 使い方:
#   ./extract_sofia_trace_by_callid.sh <CALL-ID>

CALLID="${1:-}"
if [[ -z "${CALLID}" ]]; then
  echo "usage: $0 <CALL-ID>" >&2
  exit 1
fi

LOG_MAIN="/usr/local/freeswitch/log/freeswitch.log"
LOG_ROT1="/usr/local/freeswitch/log/freeswitch.log.1"
LOG_FILE=""
if [[ -f "${LOG_MAIN}" ]]; then
  LOG_FILE="${LOG_MAIN}"
elif [[ -f "${LOG_ROT1}" ]]; then
  LOG_FILE="${LOG_ROT1}"
fi

OUT="/tmp/callid_extract_$(echo "${CALLID}" | tr '/: ' '___')_$(date +%s).txt"

echo "[extract] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo
  echo "== call-id =="
  echo "${CALLID}"
  echo
  echo "== log_file =="
  echo "${LOG_FILE}"
  echo

  if [[ -z "${LOG_FILE}" || ! -f "${LOG_FILE}" ]]; then
    echo "[error] freeswitch.log not found at ${LOG_MAIN} or ${LOG_ROT1}"
    exit 0
  fi

  echo "== freeswitch.log head (first 30) =="
  timeout 6s head -n 30 "${LOG_FILE}" || true
  echo

  echo "== match line numbers (last 200) =="
  timeout 12s grep -nF "${CALLID}" "${LOG_FILE}" | tail -n 200 || true
  echo

  echo "== context blocks (±40 lines, max 8 blocks) =="
  LINES="$(timeout 12s grep -nF "${CALLID}" "${LOG_FILE}" | tail -n 8 | cut -d: -f1 | tr '\n' ' ')"
  echo "match_lines=${LINES}"
  echo
  for ln in ${LINES:-}; do
    start=$((ln-40)); if ((start<1)); then start=1; fi
    end=$((ln+40))
    echo "---- context L${start}-L${end} (match L${ln}) ----"
    timeout 8s sed -n "${start},${end}p" "${LOG_FILE}" || true
    echo
  done

  echo "== quick SDP signals inside extracted lines (grep) =="
  timeout 12s grep -F "${CALLID}" "${LOG_FILE}" | egrep -i "c=IN IP4|m=audio|a=sendonly|a=recvonly|a=inactive|0.0.0.0|INVITE|SIP/2.0 200|ACK|RFC2543|hold method" | tail -n 200 || true
  echo

  echo "== existence check for siptrace-like phrases (last 200) =="
  timeout 10s egrep -in "RFC2543|0\\.0\\.0\\.0 hold method|siptrace|sofia.*sip" "${LOG_FILE}" | tail -n 200 || true
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
