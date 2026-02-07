#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - sofia siptrace が「どこにもSIP本体を出さない」原因を、設定変更なしで観測する。
#  - まずは fs_cli 経由でログ出力先・loglevel・logfile設定を確定させる。
#
# 使い方:
#   ./fs_logging_introspect.sh [profile]
#   例: ./fs_logging_introspect.sh lab_open

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

PROFILE="${1:-lab_open}"
OUT="/tmp/fs_logging_introspect_$(date +%s).txt"
run_fs(){ timeout 10s ${FSCLI} -x "$1" 2>/dev/null || true; }

echo "[introspect] writing: ${OUT}"
{
  echo "== date =="
  date -Is || true
  echo

  echo "== fs_cli status =="
  run_fs "status" || true
  echo

  echo "== show modules like logfile/console =="
  run_fs "show modules like logfile" || true
  run_fs "show modules like console" || true
  echo

  echo "== console loglevel =="
  run_fs "console loglevel" || true
  echo

  echo "== log levels list =="
  run_fs "log levels" || true
  echo

  echo "== logfile show (if supported) =="
  # コマンドが無い場合もある。エラーでもそのまま証拠にする。
  run_fs "logfile show" || true
  echo

  echo "== global vars (base_dir/logfile_dir if possible) =="
  run_fs "global_getvar base_dir" || true
  run_fs "global_getvar logfile_dir" || true
  echo

  echo "== sofia status profile ${PROFILE} =="
  run_fs "sofia status profile ${PROFILE}" || true
  echo

  echo "== sofia status (first 120) =="
  run_fs "sofia status" | head -n 120 || true
  echo

  echo "== siptrace toggles (global/profile) =="
  run_fs "sofia global siptrace on" || true
  run_fs "sofia profile ${PROFILE} siptrace on" || true
  echo

  echo "== hint: files present in /usr/local/freeswitch/log (top 50) =="
  timeout 10s ls -lt /usr/local/freeswitch/log | head -n 50 || true
  echo
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
