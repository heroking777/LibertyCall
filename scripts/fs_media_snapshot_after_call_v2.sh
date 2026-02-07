#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - uuid_getvar の値が不正(例: remote_media_ip=0.0.0.0)になり得るため、
#    uuid_dump を一次証拠として保存し、media関連行を抽出して整合を取る。
#  - リアルタイム監視禁止。通話後に1回だけ実行して終わる。

UUID="${1:-}"
if [[ -z "${UUID}" ]]; then
  echo "usage: $0 <UUID>" >&2
  exit 1
fi

OUT="/tmp/fs_media_snapshot_v2_${UUID}_$(date +%s).txt"
echo "[fs_media_v2] writing: ${OUT}"

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

run_fs() {
  local cmd="$1"
  timeout 8s ${FSCLI} -x "${cmd}" 2>/dev/null || true
}

{
  echo "== date =="
  date -Is || true
  echo
  echo "== uuid =="
  echo "${UUID}"
  echo

  echo "== uuid_getvar (raw) =="
  for k in remote_media_ip remote_media_port local_media_ip local_media_port \
           endpoint_disposition sip_contact_uri sip_req_uri sip_to_uri sip_from_uri \
           read_codec write_codec; do
    v="$(run_fs "uuid_getvar ${UUID} ${k}" | tr -d '\r')"
    echo "${k}: ${v}"
  done
  echo

  echo "== uuid_dump (full head 180) =="
  run_fs "uuid_dump ${UUID}" | head -n 180 || true
  echo

  echo "== uuid_dump (media lines grep) =="
  # media/rtp/codec/remote/local っぽい行を広めに拾う
  run_fs "uuid_dump ${UUID}" | egrep -i "media|rtp|remote|local|codec|addr|port" || true
  echo

  echo "== uuid_dump (sofia sdp lines grep) =="
  # SDPが含まれる場合に備えて
  run_fs "uuid_dump ${UUID}" | egrep -i "v=0|o=|c=IN IP4|m=audio|a=rtpmap|a=sendrecv|a=recvonly|a=sendonly" || true
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
