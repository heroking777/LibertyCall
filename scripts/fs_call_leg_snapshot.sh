#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - remote_media_ip=0.0.0.0 の原因切り分けのため、
#    該当UUIDのA-leg/B-leg関係(bridge_uuid/partner_uuid等)とSIP/SDP要素を通話後にスナップショットする。
#  - リアルタイム監視禁止。1回実行して終わる。

UUID="${1:-}"
if [[ -z "${UUID}" ]]; then
  echo "usage: $0 <UUID>" >&2
  exit 1
fi

OUT="/tmp/fs_call_leg_snapshot_${UUID}_$(date +%s).txt"
FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

run_fs() { timeout 10s ${FSCLI} -x "$1" 2>/dev/null || true; }

getvar() {
  local u="$1" k="$2"
  run_fs "uuid_getvar ${u} ${k}" | tr -d '\r'
}

dump_grep() {
  local u="$1" pat="$2"
  run_fs "uuid_dump ${u}" | egrep -i "${pat}" || true
}

echo "[leg] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo

  echo "== target uuid =="
  echo "${UUID}"
  echo

  echo "== key vars (target) =="
  for k in channel_name callstate read_codec write_codec \
           sip_call_id sip_req_uri sip_to_uri sip_from_uri sip_contact_uri \
           bridge_uuid partner_uuid other_leg_unique_id originatee_uuid; do
    echo "${k}: $(getvar "${UUID}" "${k}")"
  done
  echo

  echo "== media vars (target) =="
  for k in remote_media_ip remote_media_port local_media_ip local_media_port \
           endpoint_disposition rtp_use_codec_string; do
    echo "${k}: $(getvar "${UUID}" "${k}")"
  done
  echo

  echo "== uuid_dump grep (target: sdp/media/rtp) =="
  dump_grep "${UUID}" "v=0|c=IN IP4|m=audio|a=rtpmap|a=sendrecv|a=recvonly|a=sendonly|media|rtp|remote|local|codec|addr|port"
  echo

  BRIDGE="$(getvar "${UUID}" "bridge_uuid")"
  PARTNER="$(getvar "${UUID}" "partner_uuid")"
  OTHER="$(getvar "${UUID}" "other_leg_unique_id")"

  echo "== related uuids =="
  echo "bridge_uuid=${BRIDGE}"
  echo "partner_uuid=${PARTNER}"
  echo "other_leg_unique_id=${OTHER}"
  echo

  for rel in "${BRIDGE}" "${PARTNER}" "${OTHER}"; do
    if [[ -n "${rel}" && "${rel}" != "_undef_" && "${rel}" != "0" ]]; then
      echo "==== related uuid: ${rel} ===="
      echo "-- key vars --"
      for k in channel_name callstate read_codec write_codec \
               sip_call_id sip_req_uri sip_to_uri sip_from_uri sip_contact_uri; do
        echo "${k}: $(getvar "${rel}" "${k}")"
      done
      echo "-- media vars --"
      for k in remote_media_ip remote_media_port local_media_ip local_media_port endpoint_disposition; do
        echo "${k}: $(getvar "${rel}" "${k}")"
      done
      echo "-- uuid_dump grep (sdp/media) --"
      dump_grep "${rel}" "v=0|c=IN IP4|m=audio|a=rtpmap|a=sendrecv|a=recvonly|a=sendonly|media|rtp|remote|local|codec|addr|port"
      echo
    fi
  done
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
