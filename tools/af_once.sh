#!/usr/bin/env bash
set -euo pipefail

UUID_FILE="${1:-/tmp/af_real_uuid.txt}"
UUID="$(cat "$UUID_FILE" 2>/dev/null || true)"
test -n "$UUID" || { echo "ERR: no UUID in $UUID_FILE"; exit 1; }

TS="$(date +%s)"
PCAP="/tmp/af9000_once.${TS}.pcap"
FSLOG="/tmp/af_fs_once.${TS}.txt"
WSFILE="/var/log/asr-ws-sink.log"
OUT="/tmp/af_once_summary.${TS}.txt"

# tcpdump: always bounded
timeout -k 1s 4s tcpdump -i lo -nn -s0 -w "$PCAP" "tcp port 9000" >/dev/null 2>&1 || true

# bgapi start/stop (non-block)
timeout -k 1s 2s fs_cli -x "bgapi uuid_audio_fork $UUID start ws://127.0.0.1:9000 mono 16k" >/dev/null 2>&1 || true
sleep 0.6
timeout -k 1s 2s fs_cli -x "bgapi uuid_audio_fork $UUID stop" >/dev/null 2>&1 || true

# FS log extract from file (journalctl禁止)
LOG="/var/log/freeswitch/freeswitch.log"
if test -f "$LOG"; then
  egrep -i "audio_fork|lws|websocket|uuid_audio_fork|CLIENT_CONNECTION_ERROR|addPendingConnect|${UUID}" "$LOG" | tail -n 200 >"$FSLOG" || true
else
  echo "MISSING:$LOG" >"$FSLOG"
fi

{
  echo "TS=$TS"
  echo "UUID=$UUID"
  echo
  echo "=== PCAP head ==="
  timeout -k 1s 2s tcpdump -nn -r "$PCAP" 2>/dev/null | head -n 20 || true
  echo
  echo "=== FREESWITCH (tail grep) ==="
  tail -n 80 "$FSLOG" || true
  echo
  echo "=== ASR_WS_SINK tail ==="
  if test -f "$WSFILE"; then
    tail -n 80 "$WSFILE" || true
  else
    echo "MISSING:$WSFILE"
  fi
} >"$OUT"

echo "DONE: $OUT"
