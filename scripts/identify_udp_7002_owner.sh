#!/usr/bin/env bash
set -euo pipefail

OUT="/tmp/udp7002_owner_$(date +%s).txt"
PORT="7002"

echo "[identify] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo

  echo "== ss -lunp (udp:${PORT}) =="
  timeout 6s ss -lunp | grep -E ":(7002)\b" || true
  echo

  echo "== lsof (udp:${PORT}) =="
  if command -v lsof >/dev/null 2>&1; then
    timeout 6s sudo lsof -nP -iUDP:${PORT} || true
  else
    echo "lsof not found"
  fi
  echo

  echo "== fuser (udp:${PORT}) =="
  if command -v fuser >/dev/null 2>&1; then
    timeout 6s sudo fuser -n udp ${PORT} -v || true
  else
    echo "fuser not found"
  fi
  echo

  echo "== derive PIDs from ss output =="
  PIDS="$(timeout 6s ss -lunp | awk '/:7002/{print $0}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u | tr '\n' ' ')"
  echo "PIDS=${PIDS}"
  echo

  for pid in ${PIDS:-}; do
    echo "---- PID ${pid} ----"
    echo "[cmdline]"
    timeout 3s tr '\0' ' ' < /proc/${pid}/cmdline 2>/dev/null || true
    echo
    echo "[cwd]"
    timeout 3s readlink -f /proc/${pid}/cwd 2>/dev/null || true
    echo
    echo "[exe]"
    timeout 3s readlink -f /proc/${pid}/exe 2>/dev/null || true
    echo
    echo "[environ LC_*]"
    timeout 3s tr '\0' '\n' < /proc/${pid}/environ 2>/dev/null | egrep '^LC_' || true
    echo
    echo "[systemd unit (best-effort)]"
    if command -v systemctl >/dev/null 2>&1; then
      timeout 3s systemctl status ${pid} 2>/dev/null | head -n 20 || true
    fi
    echo
  done
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
