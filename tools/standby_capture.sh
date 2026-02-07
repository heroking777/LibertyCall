#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# LibertyCall READY capture helper
# ------------------------------------------------------------
# Usage: ./standby_capture.sh [duration_seconds]
# Default duration is 70 seconds. The script will:
#   1. Capture SIP+RTP traffic into /tmp/fsmon/standby_<timestamp>.pcap
#   2. Prompt the operator with "READY: いま発信して"
#   3. After capture, extract SDP (c= / m=audio) to find media IP/ports
#   4. Count RTP packets in both directions using the MEDIA IP (not SIP host)
# ------------------------------------------------------------

OUTDIR="/tmp/fsmon"
SIP_HOST="61.213.230.145"        # SIP signaling peer (may differ from SDP media IP)
FSIP="160.251.170.253"            # FS側 public IP as advertised in SDP
DURATION="${1:-70}"               # capture duration in seconds
IFACE="any"

mkdir -p "${OUTDIR}"
TS="$(date +%Y%m%d_%H%M%S)"
PCAP="${OUTDIR}/standby_${TS}.pcap"

echo "[*] Capturing ${DURATION}s -> ${PCAP}"
echo "[*] (SIP peer: ${SIP_HOST})"

CAP_FILTER="(host ${SIP_HOST} and (tcp or udp)) or (udp portrange 16384-32768)"

timeout "${DURATION}s" tcpdump -i "${IFACE}" -nn -s0 -w "${PCAP}" ${CAP_FILTER} >/dev/null 2>&1 &
TCPDUMP_PID=$!
sleep 1
echo "READY: いま発信して"
wait "${TCPDUMP_PID}" || true

echo
TOTAL_PKTS=$(tcpdump -nn -r "${PCAP}" 2>/dev/null | wc -l | tr -d ' ')
echo "[*] Capture complete. Total packets: ${TOTAL_PKTS}"

echo "[*] Extracting SDP (media IP/ports) ..."
SDP_TXT="${OUTDIR}/sdp_${TS}.txt"
tcpdump -nn -A -r "${PCAP}" "udp port 5060 or tcp port 5060" 2>/dev/null \
  | egrep -a "INVITE |SIP/2.0 200|c=IN IP4|m=audio|a=rtpmap" \
  | head -n 240 > "${SDP_TXT}" || true

echo "---- SDP snippet (saved: ${SDP_TXT}) ----"
cat "${SDP_TXT}"
echo "----------------------------------------"

# Parse latest c= and m=audio lines (simple heuristic for single-call capture)
RIP=$(grep -a "c=IN IP4" "${SDP_TXT}" | tail -n 1 | awk '{print $3}' || true)
RPORT=$(grep -a "m=audio" "${SDP_TXT}" | tail -n 1 | awk '{print $2}' || true)
# FSポートは直近2件の m=audio から 1 つ前を取得（相手と自分で2件ある想定）
FSPORT=$(grep -a "m=audio" "${SDP_TXT}" | tail -n 2 | head -n 1 | awk '{print $2}' || true)

if [[ -z "${RIP:-}" || -z "${RPORT:-}" ]]; then
  echo "[!] Could not parse media IP/port from SDP. Please inspect ${SDP_TXT}."
  exit 0
fi

if [[ -z "${FSPORT:-}" || "${FSPORT}" == "${RPORT}" ]]; then
  echo "[!] FS RTP port parse ambiguous. Set manually from SDP (see ${SDP_TXT})."
  echo "    Parsed -> Remote IP: ${RIP}, Remote port: ${RPORT}, FS port: ${FSPORT}"
  exit 0
fi

echo
echo "[*] Parsed media info"
echo "    Remote media IP : ${RIP}"
echo "    Remote RTP port : ${RPORT}"
echo "    FS RTP port     : ${FSPORT}"
echo

echo "[*] RTP packet counts (media IP基準)"
FS_TO_REMOTE=$(tcpdump -nn -r "${PCAP}" "udp and src host ${FSIP} and dst host ${RIP} and dst port ${RPORT}" 2>/dev/null | wc -l | tr -d ' ')
REMOTE_TO_FS=$(tcpdump -nn -r "${PCAP}" "udp and src host ${RIP} and dst host ${FSIP} and dst port ${FSPORT}" 2>/dev/null | wc -l | tr -d ' ')
RTP_RANGE=$(tcpdump -nn -r "${PCAP}" "udp portrange 16384-32768" 2>/dev/null | wc -l | tr -d ' ')
HOST_MEDIA=$(tcpdump -nn -r "${PCAP}" "udp and host ${RIP}" 2>/dev/null | wc -l | tr -d ' ')

echo "    FS -> Remote (${FSIP} -> ${RIP}:${RPORT}) : ${FS_TO_REMOTE} packets"
echo "    Remote -> FS (${RIP} -> ${FSIP}:${FSPORT}) : ${REMOTE_TO_FS} packets"
echo "    UDP portrange 16384-32768 total            : ${RTP_RANGE} packets"
echo "    udp and host ${RIP} total                  : ${HOST_MEDIA} packets"
echo

echo "[*] SIP BYE/CANCEL tail (参考)"
tcpdump -nn -A -r "${PCAP}" "udp port 5060 or tcp port 5060" 2>/dev/null \
  | egrep -a "BYE |CANCEL |SIP/2.0 |From:|To:|Call-ID:|CSeq:" \
  | tail -n 120 || true

echo
echo "[*] Standby capture finished."
