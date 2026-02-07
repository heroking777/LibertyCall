#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - UDP:7002 を bind している複数PIDのうち、実際に recvfrom しているPIDを短時間で証拠化する。
#  - 無限待ち禁止。timeoutで必ず止める。

OUT="/tmp/rtp7002_pid_map_$(date +%s).txt"

echo "[map] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo

  echo "== ss -lunp :7002 =="
  timeout 6s ss -lunp | grep -E ":(7002)\b" || true
  echo

  PIDS="$(timeout 6s ss -lunp | sed -n '/:7002/ s/.*pid=\([0-9]\+\).*/\1/p' | sort -u | tr '\n' ' ')"
  echo "PIDS=${PIDS}"
  echo

  if ! command -v strace >/dev/null 2>&1; then
    echo "[error] strace not found. cannot map recvfrom activity."
    exit 0
  fi

  for pid in ${PIDS:-}; do
    echo "---- PID ${pid} ----"
    echo "[cmdline]"
    timeout 3s tr '\0' ' ' < /proc/${pid}/cmdline 2>/dev/null || true
    echo
    echo "[recv* trace 5s: recvfrom/recvmsg/recvmmsg]"
    # 受信APIがrecvfrom以外の可能性があるため拡張する。
    # 5秒だけ attachして出力が出るかを見る。無限待ち禁止。
    timeout 6s sudo strace -qq -tt -e trace=recvfrom,recvmsg,recvmmsg -p "${pid}" 2>&1 | head -n 80 || true
    echo
  done
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
