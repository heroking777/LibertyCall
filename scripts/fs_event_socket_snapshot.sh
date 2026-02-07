#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - ESLで購読+OKなのに受信ゼロ(total=0/raw_first=None)の原因をFS側観測で確定する
#  - event_socket が有効か / 8021をFSがlistenしているか / ACLで落ちていないか を証拠化
#
# 使い方:
#   ./fs_event_socket_snapshot.sh

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

OUT="/tmp/fs_event_socket_snapshot_$(date +%s).txt"
run_fs(){ timeout 10s ${FSCLI} -x "$1" 2>/dev/null || true; }

CONF1="/usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml"
CONF2="/etc/freeswitch/autoload_configs/event_socket.conf.xml"

{
  echo "== date =="
  date -Is || true
  echo

  echo "== fs version/status =="
  run_fs "version" || true
  run_fs "status" || true
  echo

  echo "== modules: event_socket/logfile/console =="
  run_fs "show modules like event_socket" || true
  run_fs "show modules like logfile" || true
  run_fs "show modules like console" || true
  echo

  echo "== check if 8021 is listening (ss) =="
  timeout 10s ss -lntp | egrep '(:8021|Local Address)' || true
  echo

  echo "== check if 8021 is listening (netstat if available) =="
  timeout 10s bash -lc 'command -v netstat >/dev/null 2>&1 && netstat -lntp | egrep "(:8021|Proto)" || true' || true
  echo

  echo "== event_socket config file candidates =="
  for f in "${CONF1}" "${CONF2}"; do
    if [ -f "${f}" ]; then
      echo "[found] ${f}"
      timeout 10s ls -l "${f}" || true
      echo "-- grep listen-ip/listen-port/password/acl --"
      timeout 10s egrep -n 'listen-ip|listen-port|password|acl|apply-inbound-acl' "${f}" || true
      echo
    else
      echo "[missing] ${f}"
    fi
  done
  echo

  echo "== FS can read vars? (base_dir/logfile_dir) =="
  run_fs "global_getvar base_dir" || true
  run_fs "global_getvar logfile_dir" || true
  echo

  echo "== done =="
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
