#!/usr/bin/env bash
set -euo pipefail

# 目的:
#  - 通話は最小回数(=1回)に圧縮するため、1回の通話で必要な証拠を全部まとめて回収するランナー。
#  - リアルタイム監視は禁止。prepで準備→ユーザー通話→collectでオフライン回収。
#
# 使い方:
#   ./run_one_call_evidence_bundle.sh prep
#   # ユーザーが通話10秒→終了し UUID を渡す
#   ./run_one_call_evidence_bundle.sh collect <UUID>

MODE="${1:-}"
UUID="${2:-}"
TS="$(date +%s)"

OUT="/tmp/one_call_bundle_${MODE}_${TS}.txt"

SCRIPT_DIR="/opt/libertycall/scripts"

require_file() {
  local f="$1"
  if [[ ! -x "${f}" ]]; then
    echo "[error] required script not executable: ${f}"
    exit 1
  fi
}

echo "[bundle] writing: ${OUT}"

{
  echo "== date =="
  date -Is || true
  echo "== mode =="
  echo "${MODE}"
  echo

  if [[ "${MODE}" == "prep" ]]; then
    require_file "${SCRIPT_DIR}/fs_sofia_siptrace_burst.sh"
    echo "== siptrace prep =="
    timeout 25s "${SCRIPT_DIR}/fs_sofia_siptrace_burst.sh" prep || true
    echo

    echo "== ss -lunp :7002 =="
    timeout 6s ss -lunp | grep -E ":(7002)\\b" || true
    echo

    echo "== systemd actives =="
    timeout 6s systemctl is-active liberty_gateway.service libertycall-rtp.service 2>/dev/null || true
    echo

    echo "NOTE: Do NOT wait. Tell user to make 10s call and provide UUID."
    echo

  elif [[ "${MODE}" == "collect" ]]; then
    if [[ -z "${UUID}" ]]; then
      echo "usage: $0 collect <UUID>"
      exit 1
    fi
    require_file "${SCRIPT_DIR}/fs_call_leg_snapshot.sh"
    require_file "${SCRIPT_DIR}/fs_media_snapshot_after_call_v2.sh"
    require_file "${SCRIPT_DIR}/fs_sip_sdp_extract_after_call.sh"
    require_file "${SCRIPT_DIR}/fs_sofia_siptrace_burst.sh"
    if [[ -x "${SCRIPT_DIR}/capture_rtp_7002_pcap.sh" ]]; then
      HAS_PCAP=1
    else
      HAS_PCAP=0
    fi

    echo "== uuid =="
    echo "${UUID}"
    echo

    echo "== call leg snapshot =="
    timeout 30s "${SCRIPT_DIR}/fs_call_leg_snapshot.sh" "${UUID}" || true
    echo

    echo "== media snapshot v2 =="
    timeout 25s "${SCRIPT_DIR}/fs_media_snapshot_after_call_v2.sh" "${UUID}" || true
    echo

    echo "== sip/sdp extract (from freeswitch.log) =="
    timeout 25s "${SCRIPT_DIR}/fs_sip_sdp_extract_after_call.sh" "${UUID}" || true
    echo

    # CALL-ID を取り直して siptrace collect のKEYに使う（空ならUUIDでgrep）
    CALL_ID="$(timeout 8s fs_cli -x "uuid_getvar ${UUID} sip_call_id" 2>/dev/null | tr -d '\r' || true)"
    if [[ -z "${CALL_ID}" || "${CALL_ID}" == "_undef_" ]]; then
      CALL_ID="${UUID}"
    fi
    echo "== siptrace collect (KEY=${CALL_ID}) =="
    timeout 35s "${SCRIPT_DIR}/fs_sofia_siptrace_burst.sh" collect "${CALL_ID}" || true
    echo

    if [[ "${HAS_PCAP}" == "1" ]]; then
      echo "== pcap capture 7002 =="
      timeout 30s "${SCRIPT_DIR}/capture_rtp_7002_pcap.sh" || true
      echo
      echo "== pcap summary (if exists) =="
      timeout 6s sed -n '1,120p' /tmp/rtp_7002_last_summary.txt 2>/dev/null || true
      echo
    else
      echo "== pcap capture 7002 =="
      echo "(capture_rtp_7002_pcap.sh not found/executable)"
      echo
    fi

    echo "== done =="
    echo "Collected evidence for UUID=${UUID}"
    echo
  else
    echo "[error] unknown mode: ${MODE}"
    exit 1
  fi
} | tee "${OUT}" >/dev/null

echo "[ok] ${OUT}"
