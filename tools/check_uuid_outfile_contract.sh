#!/usr/bin/env bash
set -euo pipefail

f="${1:-}"
[[ -n "$f" && -f "$f" ]] || { echo "NG: usage $0 /tmp/call_uuid_*.txt"; exit 2; }

need_keys=(UUID FINAL_REASON FINAL_MATCH_STRATEGY DIAG_EXIT_RC DIAG_LAST_CMD DIAG_LAST_LINENO)
missing=()

has_key() { grep -q "^$1=" "$f"; }

for k in "${need_keys[@]}"; do
  if ! has_key "$k"; then
    missing+=("$k")
  fi
done

if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "NG: missing_keys=${missing[*]}"
  exit 2
fi

last_kv() { tac "$f" | grep -m1 "^$1=" | cut -d= -f2- || true; }

uuid="$(last_kv UUID)"
fr="$(last_kv FINAL_REASON)"
fm="$(last_kv FINAL_MATCH_STRATEGY)"

if [[ -n "$uuid" && "$uuid" != "none" ]]; then
  if ! echo "$fr" | grep -q '^ok_by_'; then
    echo "NG: FINAL_REASON_not_ok_by_ ($fr)"
    exit 2
  fi
  if ! echo "$fm" | grep -q '^ok_by_'; then
    echo "NG: FINAL_MATCH_STRATEGY_not_ok_by_ ($fm)"
    exit 2
  fi
fi

echo "OK"
exit 0
