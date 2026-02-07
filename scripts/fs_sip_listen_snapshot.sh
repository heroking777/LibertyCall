#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - "通話SIP(INVITE/200/ACK+SDP)"が実際にどのIP:portで流れているかを確定する
#  - pcapのフィルタ条件を推測で決めない

TS="$(date +%s)"
OUT="/tmp/fs_sip_listen_snapshot_${TS}.log"

need(){ command -v "$1" >/dev/null 2>&1 || { echo "[error] missing: $1" >&2; exit 1; }; }
need timeout
need ss
need fs_cli

{
  echo "== date =="; date -Iseconds
  echo
  echo "== sofia status ==";
  timeout 12s fs_cli -x "sofia status" || true
  echo
  echo "== sofia status profile lab_open ==";
  timeout 12s fs_cli -x "sofia status profile lab_open" || true
  echo
  echo "== ss candidates (common SIP ports) ==";
  timeout 10s ss -lntup | egrep ":(5060|5061|5080|5081|5090)\b" || true
  echo
  echo "== ss all freeswitch listen sockets ==";
  timeout 10s ss -lntup | grep -i freeswitch || true
} | tee "${OUT}" >/dev/null

echo "[ok] saved ${OUT}"
echo "report: which SIP port(s) freeswitch listens on for lab_open and overall."
