#!/usr/bin/env bash

set -e

cd /opt/libertycall

echo "[DEV] Stopping libertycall.service (if running) ..."
sudo systemctl stop libertycall.service 2>/dev/null || true

echo "[DEV] Freeing RTP port 7100 ..."
./scripts/free_rtp_7100.sh

echo "[DEV] Activating venv ..."
# shellcheck disable=SC1091
source venv/bin/activate

echo "[DEV] Starting gateway/realtime_gateway.py ..."
exec python gateway/realtime_gateway.py



























