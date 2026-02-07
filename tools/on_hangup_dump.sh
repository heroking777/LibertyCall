#!/bin/bash
set -euo pipefail
UUID="$1"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="/tmp/fsmon"
mkdir -p "$OUT_DIR"
fs_cli -x "uuid_dump $UUID" > "$OUT_DIR/uuid_dump_${TS}_${UUID}.txt" 2>&1 || echo "$(date -Is) uuid_dump failed for $UUID" >> "$OUT_DIR/hangup_capture.log"
tail -n 200 /usr/local/freeswitch/log/freeswitch.log > "$OUT_DIR/logtail_${TS}_${UUID}.txt" 2>&1 || echo "$(date -Is) log tail failed for $UUID" >> "$OUT_DIR/hangup_capture.log"
echo "$(date -Is) captured $UUID" >> "$OUT_DIR/hangup_capture.log"
