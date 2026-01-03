#!/usr/bin/env bash
set -euo pipefail

f="${1:-}"
if [[ -z "${f}" || ! -f "${f}" ]]; then
  echo "usage: $0 /tmp/call_uuid_*.txt" >&2
  exit 2
fi

last_kv() {
  local key="$1"
  tac "$f" | grep -m1 "^${key}=" | cut -d= -f2- || true
}

uuid="$(last_kv UUID)"
final_reason="$(last_kv FINAL_REASON)"
final_ms="$(last_kv FINAL_MATCH_STRATEGY)"

callid_cnt="$(last_kv CALLID_CAND_CNT)"
ext_cnt="$(last_kv EXT_CAND_CNT)"
tw_cnt="$(last_kv TIMEWINDOW_CAND_CNT)"
latest_cnt="$(last_kv LATEST_CAND_CNT)"

callid_cnt="${callid_cnt:-0}"
ext_cnt="${ext_cnt:-0}"
tw_cnt="${tw_cnt:-0}"
latest_cnt="${latest_cnt:-0}"

has_mismatch="0"
if tac "$f" | grep -q '^DIAG_CALLID_MISMATCH_'; then
  has_mismatch="1"
fi

if [[ -z "${final_reason}" ]]; then
  final_reason="(missing)"
fi
if [[ -z "${final_ms}" ]]; then
  final_ms="(missing)"
fi

cls="C"
hint="unknown"

if [[ -n "${uuid}" && "${uuid}" != "none" ]]; then
  cls="OK"
  hint="uuid_resolved"
  if [[ "${final_reason}" == "(missing)" ]]; then
    hint="uuid_resolved_but_final_reason_missing"
  fi
else
  if [[ "${callid_cnt}" == "0" && "${ext_cnt}" == "0" && "${tw_cnt}" == "0" && "${latest_cnt}" == "0" ]]; then
    cls="A"
    hint="no_candidates_any_strategy"
  else
    if grep -q 'no_candidates' <<<"${final_reason}"; then
      cls="C"
      hint="contradiction_cnt_nonzero_but_no_candidates"
    elif [[ "${has_mismatch}" == "1" ]]; then
      cls="B"
      hint="candidates_exist_but_callid_var_mismatch"
    else
      cls="C"
      hint="candidates_exist_but_not_selected_or_unknown"
    fi
  fi
fi

echo "UUID=${uuid}"
echo "FINAL_REASON=${final_reason}"
echo "FINAL_MATCH_STRATEGY=${final_ms}"
echo "CLASS=${cls}"
echo "HINT=${hint}"
