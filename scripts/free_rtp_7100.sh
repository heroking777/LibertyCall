#!/usr/bin/env bash

set -e

PORT=7100

echo "[FREE_RTP] Killing existing gateway processes (if any) ..."

# gateway/realtime_gateway.py を使っている Python プロセスを全部 kill
PIDS="$(pgrep -f 'gateway/realtime_gateway.py' || true)"

if [ -n "$PIDS" ]; then
  echo "[FREE_RTP] Found PIDs: $PIDS"
  sudo kill $PIDS || true
  sleep 1
else
  echo "[FREE_RTP] No realtime_gateway.py process found."
fi

echo "[FREE_RTP] Checking port ${PORT} ..."

if sudo ss -lunp | grep -q ":${PORT} "; then
  echo "[FREE_RTP] Port ${PORT} is STILL in use:"
  sudo ss -lunp | grep ":${PORT} "
  exit 1
else
  echo "[FREE_RTP] Port ${PORT} is free."
fi

exit 0
