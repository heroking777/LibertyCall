#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - /var/log/freeswitch/freeswitch.log が無い環境で、FreeSWITCHのログ出力先をオフラインで確定する。
#  - リアルタイム監視禁止。1回実行して終わる。

OUT="/tmp/fs_log_locator_$(date +%s).txt"
FSCLI="fs_cli"

echo "[fs_log_locator] writing: ${OUT}"

if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

run_fs() { timeout 8s ${FSCLI} -x "$1" 2>/dev/null || true; }

{
  echo "== date =="
  date -Is || true
  echo

  echo "== fs status =="
  run_fs "status" | head -n 30 || true
  echo

  echo "== filesystem candidates =="
  for d in /var/log/freeswitch /usr/local/freeswitch/log /opt/freeswitch/log /var/lib/freeswitch/log /tmp; do
    if [[ -d "$d" ]]; then
      echo "-- ls -la $d (head) --"
      timeout 6s ls -la "$d" | head -n 80 || true
      echo
    fi
  done

  echo "== freeswitch vars (if any) =="
  # vars は大量になり得るので head のみ
  run_fs "global_getvar logfile_dir" | head -n 20 || true
  run_fs "global_getvar log_dir" | head -n 20 || true
  run_fs "global_getvar base_dir" | head -n 20 || true
  echo

  echo "== modules loaded (log modules) =="
  run_fs "show modules" | egrep -i "logfile|console|sofia|event_socket" | head -n 80 || true
  echo

  echo "== sofia profiles =="
  run_fs "sofia status" | head -n 80 || true
  echo

  echo "== hint: filesystem search for 'freeswitch.log' (limited) =="
  # 深掘りし過ぎると遅いので /var /usr/local /opt のみ限定
  timeout 20s bash -lc "find /var /usr/local /opt -maxdepth 4 -type f -name 'freeswitch*.log*' 2>/dev/null | head -n 200" || true
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
