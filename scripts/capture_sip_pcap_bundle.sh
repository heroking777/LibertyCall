#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - ESLイベントが取れない環境でも、SIP/SDP本体をネットワーク層で確実に回収する
#  - 「c=IN IP4 0.0.0.0」が offer/answer/hold のどれ由来かを1回の通話で確定する
#
# 使い方:
#   # 通話前準備（通話しない）
#   ./capture_sip_pcap_bundle.sh prep
#
#   # 通話前にキャプチャ開始（待機しない: timeoutで自動停止）
#   ./capture_sip_pcap_bundle.sh capture
#   -> ここでユーザーが通話10秒して切る（AIは待たない）
#
#   # 通話後に解析
#   ./capture_sip_pcap_bundle.sh analyze /tmp/sipcap_<ts>.pcap

MODE="${1:-}"
TS="$(date +%s)"
OUT_PCAP="/tmp/sipcap_${TS}.pcap"
OUT_TXT="/tmp/sipcap_${TS}.txt"
OUT_SUM="/tmp/sipcap_${TS}_summary.txt"

need(){ command -v "$1" >/dev/null 2>&1 || { echo "[error] missing: $1" >&2; exit 1; }; }
need timeout
need tcpdump
need ip

guess_if(){
  # best-effort: default route dev
  ip route get 1.1.1.1 2>/dev/null | awk '/dev/ {for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}'
}

PORT_FILTER="(port 5060 or port 5080 or port 5061)"

prep(){
  local IF
  IF="$(guess_if)"
  echo "== prep =="
  echo "iface=${IF:-unknown}"
  echo "port_filter=${PORT_FILTER}"
  echo "example:"
  echo "  $0 capture"
  echo "  $0 analyze ${OUT_PCAP}"
}

capture(){
  local IF
  IF="$(guess_if)"
  if [ -z "${IF}" ]; then
    echo "[error] could not detect interface via routing. set IFACE env and retry." >&2
    exit 1
  fi
  echo "== capture =="
  echo "iface=${IF}"
  echo "out=${OUT_PCAP}"
  echo "NOTE: this command returns immediately after tcpdump timeout ends."
  # 30秒で自動停止。ユーザーはその間に通話10秒→切断する想定。
  timeout 32s tcpdump -i "${IF}" -s 0 -w "${OUT_PCAP}" "${PORT_FILTER}" >/dev/null 2>&1 || true
  echo "[ok] saved ${OUT_PCAP}"
  echo "next: $0 analyze ${OUT_PCAP}"
}

analyze(){
  local PCAP="${1:-}"
  if [ -z "${PCAP}" ] || [ ! -f "${PCAP}" ]; then
    echo "[error] pcap not found: ${PCAP}" >&2
    exit 1
  fi
  echo "== analyze =="
  echo "pcap=${PCAP}"
  local BASE
  BASE="$(basename "${PCAP}" .pcap)"
  OUT_TXT="/tmp/${BASE}.txt"
  OUT_SUM="/tmp/${BASE}_summary.txt"

  # packet count
  local CNT
  CNT="$(timeout 20s tcpdump -r "${PCAP}" 2>/dev/null | wc -l | tr -d ' ')"
  echo "packet_count=${CNT}" | tee "${OUT_SUM}" >/dev/null

  # ASCII dump
  timeout 25s tcpdump -r "${PCAP}" -A 2>/dev/null > "${OUT_TXT}" || true

  {
    echo "== key lines (with line numbers) =="
    egrep -n '^(INVITE|ACK|SIP/2\.0 200)|c=IN IP4|m=audio|a=(sendonly|recvonly|inactive)' "${OUT_TXT}" || true
    echo
    echo "== occurrences of 0.0.0.0 =="
    egrep -n '0\.0\.0\.0' "${OUT_TXT}" || true
  } >> "${OUT_SUM}"

  echo "[ok] ${OUT_TXT}"
  echo "[ok] ${OUT_SUM}"
  echo "report these facts only:"
  echo " - packet_count"
  echo " - in _summary: which start-line block contains c=IN IP4 0.0.0.0 (INVITE? 200? other?)"
}

case "${MODE}" in
  prep) prep ;;
  capture) capture ;;
  analyze) analyze "${2:-}" ;;
  *) echo "usage: $0 {prep|capture|analyze <pcap>}" >&2; exit 2 ;;
esac
