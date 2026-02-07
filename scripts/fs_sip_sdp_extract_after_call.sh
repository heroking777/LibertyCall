#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - call-idがfreeswitch.logに出ない環境でも、UUIDから取得できる複数キーで
#    SIP/SDP関連ログをオフライン抽出する。
#  - リアルタイム監視は禁止。通話後に1回だけ実行して終わる。
#
# 使い方:
#   ./fs_sip_sdp_extract_after_call.sh <UUID>

UUID="${1:-}"
if [[ -z "${UUID}" ]]; then
  echo "usage: $0 <UUID>" >&2
  exit 1
fi

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

# 本環境では /usr/local/freeswitch/log/ 配下に存在することが確定済み
LOG_MAIN="/usr/local/freeswitch/log/freeswitch.log.1"
LOG_ROT1="/usr/local/freeswitch/log/freeswitch.log"
LOG_FALLBACK_MAIN="/var/log/freeswitch/freeswitch.log"
LOG_FALLBACK_ROT1="/var/log/freeswitch/freeswitch.log.1"

OUT="/tmp/fs_sip_sdp_extract_${UUID}_$(date +%s).txt"
echo "[sip_sdp] writing: ${OUT}"

run_fs() { timeout 8s ${FSCLI} -x "$1" 2>/dev/null || true; }

getv() {
  local k="$1"
  run_fs "uuid_getvar ${UUID} ${k}" | tr -d '\r'
}

CALL_ID="$(getv "sip_call_id")"
SIP_FROM_USER="$(getv "sip_from_user")"
SIP_TO_USER="$(getv "sip_to_user")"
SIP_REQ_USER="$(getv "sip_req_user")"
SIP_REQ_HOST="$(getv "sip_req_host")"
SIP_REQ_URI="$(getv "sip_req_uri")"
CALLER_ID_NUMBER="$(getv "caller_id_number")"
DESTINATION_NUMBER="$(getv "destination_number")"
CHANNEL_NAME="$(getv "channel_name")"

if [[ -z "${CALL_ID}" || "${CALL_ID}" == "_undef_" ]]; then CALL_ID=""; fi
if [[ -z "${SIP_FROM_USER}" || "${SIP_FROM_USER}" == "_undef_" ]]; then SIP_FROM_USER=""; fi
if [[ -z "${SIP_TO_USER}" || "${SIP_TO_USER}" == "_undef_" ]]; then SIP_TO_USER=""; fi
if [[ -z "${SIP_REQ_USER}" || "${SIP_REQ_USER}" == "_undef_" ]]; then SIP_REQ_USER=""; fi
if [[ -z "${SIP_REQ_HOST}" || "${SIP_REQ_HOST}" == "_undef_" ]]; then SIP_REQ_HOST=""; fi
if [[ -z "${SIP_REQ_URI}" || "${SIP_REQ_URI}" == "_undef_" ]]; then SIP_REQ_URI=""; fi
if [[ -z "${CALLER_ID_NUMBER}" || "${CALLER_ID_NUMBER}" == "_undef_" ]]; then CALLER_ID_NUMBER=""; fi
if [[ -z "${DESTINATION_NUMBER}" || "${DESTINATION_NUMBER}" == "_undef_" ]]; then DESTINATION_NUMBER=""; fi
if [[ -z "${CHANNEL_NAME}" || "${CHANNEL_NAME}" == "_undef_" ]]; then CHANNEL_NAME=""; fi

pick_log() {
  if [[ -f "${LOG_MAIN}" ]]; then
    echo "${LOG_MAIN}"
  elif [[ -f "${LOG_ROT1}" ]]; then
    echo "${LOG_ROT1}"
  elif [[ -f "${LOG_FALLBACK_MAIN}" ]]; then
    echo "${LOG_FALLBACK_MAIN}"
  elif [[ -f "${LOG_FALLBACK_ROT1}" ]]; then
    echo "${LOG_FALLBACK_ROT1}"
  else
    echo ""
  fi
}

LOG_FILE="$(pick_log)"

# 複数キーを候補として並べる（空は無視）
KEYS=()
[[ -n "${CALL_ID}" ]] && KEYS+=("${CALL_ID}")
[[ -n "${SIP_REQ_URI}" ]] && KEYS+=("${SIP_REQ_URI}")
[[ -n "${SIP_REQ_USER}" ]] && KEYS+=("${SIP_REQ_USER}")
[[ -n "${SIP_FROM_USER}" ]] && KEYS+=("${SIP_FROM_USER}")
[[ -n "${CALLER_ID_NUMBER}" ]] && KEYS+=("${CALLER_ID_NUMBER}")
[[ -n "${DESTINATION_NUMBER}" ]] && KEYS+=("${DESTINATION_NUMBER}")
[[ -n "${UUID}" ]] && KEYS+=("${UUID}")

{
  echo "== date =="
  date -Is || true
  echo

  echo "== uuid =="
  echo "${UUID}"
  echo

  echo "== sip vars =="
  echo "sip_call_id=${CALL_ID}"
  echo "sip_from_user=${SIP_FROM_USER}"
  echo "sip_to_user=${SIP_TO_USER}"
  echo "sip_req_user=${SIP_REQ_USER}"
  echo "sip_req_host=${SIP_REQ_HOST}"
  echo "sip_req_uri=${SIP_REQ_URI}"
  echo "caller_id_number=${CALLER_ID_NUMBER}"
  echo "destination_number=${DESTINATION_NUMBER}"
  echo "channel_name=${CHANNEL_NAME}"
  echo

  echo "== uuid_dump sdp excerpt (uuid_dump grep) =="
  run_fs "uuid_dump ${UUID}" | egrep -i "v=0|c=IN IP4|m=audio|a=rtpmap|a=sendrecv|a=recvonly|a=sendonly|a=inactive|remote|local|media|rtp|port|addr|codec" || true
  echo

  echo "== log_file =="
  echo "${LOG_FILE}"
  echo

  if [[ -z "${LOG_FILE}" ]]; then
    echo "[error] freeswitch log not found"
    exit 0
  fi

  echo "== keys =="
  printf '%s\n' "${KEYS[@]:-}" || true
  echo

  echo "== matches by keys (line numbers, tail 200 each) =="
  for k in "${KEYS[@]:-}"; do
    [[ -z "${k}" ]] && continue
    echo "-- key=${k} --"
    timeout 10s grep -nF "${k}" "${LOG_FILE}" | tail -n 200 || true
    echo
  done
  echo

  echo "== siptrace-like phrases (last 300) =="
  timeout 10s egrep -in "RFC2543|0\\.0\\.0\\.0 hold method|siptrace|INVITE|SIP/2\\.0 200|ACK|c=IN IP4|m=audio|a=sendonly|a=recvonly|a=inactive" "${LOG_FILE}" | tail -n 300 || true
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
