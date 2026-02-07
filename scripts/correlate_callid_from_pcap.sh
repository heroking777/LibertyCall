#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - SIP pcapのCall-IDとFreeSWITCH側ログ/UUIDを相関し、
#    「pcap上のSDP」と「FSが採用したremote_media_ip」がズレる原因を確定する
#
# 使い方:
#   ./correlate_callid_from_pcap.sh /tmp/sipcap_xxx.pcap
#   ./correlate_callid_from_pcap.sh /tmp/sipcap_xxx.pcap --callid "<Call-ID>"

PCAP="${1:-}"
if [ -z "${PCAP}" ] || [ ! -f "${PCAP}" ]; then
  echo "[error] pcap not found: ${PCAP}" >&2
  exit 1
fi

CALLID_ARG=""
if [ "${2:-}" = "--callid" ]; then
  CALLID_ARG="${3:-}"
fi

need(){ command -v "$1" >/dev/null 2>&1 || { echo "[error] missing: $1" >&2; exit 1; }; }
need timeout
need tcpdump
need grep
need sed
need awk

LOGDIR="/usr/local/freeswitch/log"
LOG1="${LOGDIR}/freeswitch.log.1"
LOG0="${LOGDIR}/freeswitch.log"
if [ ! -f "${LOG1}" ] && [ ! -f "${LOG0}" ]; then
  echo "[error] freeswitch log not found under ${LOGDIR}" >&2
  exit 1
fi

TS="$(date +%s)"
OUT="/tmp/correlate_${TS}.txt"

TMP_TXT="/tmp/pcap_ascii_${TS}.txt"
timeout 25s tcpdump -r "${PCAP}" -A 2>/dev/null > "${TMP_TXT}" || true

CALLIDS_ALL="$(grep -aE '^Call-ID:' "${TMP_TXT}" | sed 's/^Call-ID:[[:space:]]*//' | awk 'NF' | sort -u || true)"

pick_callid(){
  if [ -n "${CALLID_ARG}" ]; then
    echo "${CALLID_ARG}"
    return
  fi
  # prefer a Call-ID whose SDP contains c=IN IP4 0.0.0.0 (RFC2543 hold symptom)
  local CID
  CID="$(awk '
    BEGIN{cid=""; has000=0;}
    /^Call-ID:/ {cid=$0; sub(/^Call-ID:[ \t]*/, "", cid); has000=0}
    /c=IN IP4 0\.0\.0\.0/ {if(cid!=""){has000=1}}
    /^$/ { if(cid!="" && has000==1){print cid} }
  ' "${TMP_TXT}" | tail -n 1 || true)"
  if [ -n "${CID}" ]; then
    echo "${CID}"
    return
  fi
  # fallback: last seen Call-ID
  grep -aE '^Call-ID:' "${TMP_TXT}" | tail -n 1 | sed 's/^Call-ID:[[:space:]]*//' || true
}

CALLID="$(pick_callid)"

search_logs(){
  local CID="$1"
  local LOGF="$2"
  if [ ! -f "${LOGF}" ]; then
    return
  fi
  echo "== log file =="; echo "${LOGF}"
  echo "== log match line numbers (Call-ID) =="
  grep -nF "${CID}" "${LOGF}" | head -n 20 || true
  echo
  local LNO
  LNO="$(grep -nF "${CID}" "${LOGF}" | head -n 1 | cut -d: -f1 || true)"
  if [ -n "${LNO}" ]; then
    local START END
    START=$((LNO-200)); if [ "${START}" -lt 1 ]; then START=1; fi
    END=$((LNO+200))
    echo "== log slice (${START}-${END}) =="
    sed -n "${START},${END}p" "${LOGF}" || true
    echo
    echo "== UUID candidates in slice =="
    sed -n "${START},${END}p" "${LOGF}" | grep -aoE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | sort -u || true
    echo
    echo "== key phrases in slice =="
    sed -n "${START},${END}p" "${LOGF}" | egrep -n 'RFC2543|remote_media_(ip|port)|c=IN IP4|m=audio|sendonly|recvonly|inactive' || true
  else
    echo "== log slice =="
    echo "[warn] no Call-ID match in ${LOGF}"
  fi
  echo
}

{
  echo "== date =="; date -Is || true
  echo "== pcap =="; echo "${PCAP}"
  echo "== logs =="; echo "${LOG1}"; echo "${LOG0}"
  echo
  echo "== Call-IDs in pcap (unique) =="
  if [ -n "${CALLIDS_ALL}" ]; then
    echo "${CALLIDS_ALL}"
  else
    echo "<none>"
  fi
  echo

  echo "== selected Call-ID =="
  echo "${CALLID:-<none>}"
  echo

  echo "== pcap key lines =="
  grep -aEn '^(INVITE|ACK|SIP/2\.0 200)|^Call-ID:|c=IN IP4|m=audio|a=(sendonly|recvonly|inactive)' "${TMP_TXT}" || true
  echo

  if [ -n "${CALLID}" ]; then
    search_logs "${CALLID}" "${LOG1}"
    search_logs "${CALLID}" "${LOG0}"
  else
    echo "[warn] no selected Call-ID"
  fi
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
