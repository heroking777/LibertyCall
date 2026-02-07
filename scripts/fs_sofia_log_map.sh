#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - sofia/siptrace/RFC2543/hold/0.0.0.0 が「どのログファイルに出ているか」を機械的に確定する。
#  - CALL-ID/UUIDがfreeswitch.logに出ない状況で、ログ所在ミスを潰す。
#
# 使い方:
#   ./fs_sofia_log_map.sh

LOGDIR="/usr/local/freeswitch/log"
OUT="/tmp/fs_sofia_log_map_$(date +%s).txt"

echo "[map] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo

  echo "== logdir =="
  echo "${LOGDIR}"
  echo

  echo "== candidates (top 80 by mtime) =="
  timeout 12s ls -lt "${LOGDIR}" | head -n 80 || true
  echo

  echo "== pattern counts per file (tail 200) =="
  # 対象を広めに。gzipは重いので今回は除外（必要なら次ターンで対応）。
  PAT='RFC2543|0\.0\.0\.0 hold method|siptrace|sofia.*sip|c=IN IP4 0\.0\.0\.0|a=sendonly|a=recvonly|a=inactive'
  for f in "${LOGDIR}"/*.log "${LOGDIR}"/*.log.[0-9] "${LOGDIR}"/freeswitch.log "${LOGDIR}"/freeswitch.log.1 "${LOGDIR}"/*.bak.*; do
    [[ -f "$f" ]] || continue
    c="$(timeout 8s egrep -aic "${PAT}" "$f" 2>/dev/null || true)"
    if [[ -n "${c}" && "${c}" != "0" ]]; then
      echo "count=${c} file=${f}"
    fi
  done | tail -n 200
  echo

  echo "== sample lines (last 6) from files with matches =="
  for f in "${LOGDIR}"/*.log "${LOGDIR}"/*.log.[0-9] "${LOGDIR}"/freeswitch.log "${LOGDIR}"/freeswitch.log.1 "${LOGDIR}"/*.bak.*; do
    [[ -f "$f" ]] || continue
    c="$(timeout 6s egrep -aic "${PAT}" "$f" 2>/dev/null || true)"
    if [[ -n "${c}" && "${c}" != "0" ]]; then
      echo "---- file=${f} (count=${c}) ----"
      timeout 10s egrep -ain "${PAT}" "$f" 2>/dev/null | tail -n 6 || true
      echo
    fi
  done
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
