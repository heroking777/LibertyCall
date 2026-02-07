#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - SIP本体（INVITE/200/ACK + SDP）を「ログ設定に依存せず」回収する。
#  - fs_cli の event plain で SOFIA::sip を短時間だけ購読し、/tmp に保存して終了する。
#  - リアルタイム待機は禁止：timeoutで強制終了する。
#
# 使い方:
#   ./fs_event_sofia_sip_burst.sh [seconds] [profile]
#   例: ./fs_event_sofia_sip_burst.sh 12 lab_open

SECS="${1:-12}"
PROFILE="${2:-lab_open}"
OUT="/tmp/fs_event_sofia_sip_burst_$(date +%s).log"

FSCLI="fs_cli"
if ! command -v ${FSCLI} >/dev/null 2>&1; then
  echo "[error] fs_cli not found" >&2
  exit 1
fi

echo "[burst] writing: ${OUT}"

# siptraceは既にONだが、念のため（失敗しても継続）
timeout 6s ${FSCLI} -x "sofia global siptrace on" >/dev/null 2>&1 || true
timeout 6s ${FSCLI} -x "sofia profile ${PROFILE} siptrace on" >/dev/null 2>&1 || true

# event購読（SOFIA::sip は生SIPを含むことが多い）
# - timeoutで強制終了
# - バッファリング抑制のため stdbuf を使う（無ければそのまま）
if command -v stdbuf >/dev/null 2>&1; then
  timeout "${SECS}s" stdbuf -oL -eL ${FSCLI} -x "event plain SOFIA::sip" > "${OUT}" 2>&1 || true
else
  timeout "${SECS}s" ${FSCLI} -x "event plain SOFIA::sip" > "${OUT}" 2>&1 || true
fi

echo "[ok] ${OUT}"
