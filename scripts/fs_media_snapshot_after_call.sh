#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - 通話後にFreeSWITCHから media の実宛先(remote_media_ip/remote_media_port等)をスナップショット取得する。
#  - 7002へ送っていないなら、Gateway側7002計測は無意味なので、まず宛先を確定する。
#  - リアルタイム監視禁止。1回実行で終わる。
#
# 使い方:
#   ./fs_media_snapshot_after_call.sh <UUID>

UUID="${1:-}"
if [[ -z "${UUID}" ]]; then
  echo "usage: $0 <UUID>" >&2
  exit 1
fi

OUT="/tmp/fs_media_snapshot_${UUID}_$(date +%s).txt"
echo "[fs_media] writing: ${OUT}"

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

run_fs() {
  local cmd="$1"
  timeout 6s ${FSCLI} -x "${cmd}" 2>/dev/null || true
}

{
  echo "== date =="
  date -Is || true
  echo

  echo "== uuid =="
  echo "${UUID}"
  echo

  echo "== show channels (filtered) =="
  run_fs "show channels like ${UUID}" | head -n 50 || true
  echo

  echo "== uuid_dump (head) =="
  run_fs "uuid_dump ${UUID}" | head -n 120 || true
  echo

  echo "== media vars =="
  echo "remote_media_ip:   $(run_fs "uuid_getvar ${UUID} remote_media_ip" | tr -d '\r')"
  echo "remote_media_port: $(run_fs "uuid_getvar ${UUID} remote_media_port" | tr -d '\r')"
  echo "local_media_ip:    $(run_fs "uuid_getvar ${UUID} local_media_ip" | tr -d '\r')"
  echo "local_media_port:  $(run_fs "uuid_getvar ${UUID} local_media_port" | tr -d '\r')"
  echo "read_codec:        $(run_fs "uuid_getvar ${UUID} read_codec" | tr -d '\r')"
  echo "write_codec:       $(run_fs "uuid_getvar ${UUID} write_codec" | tr -d '\r')"
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
