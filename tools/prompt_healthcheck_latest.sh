#!/usr/bin/env bash
set -euo pipefail

LOG="${1:-/usr/local/freeswitch/log/freeswitch.log}"
MINUTES="${MINUTES:-15}"

[[ -f "$LOG" ]] || { echo "NG: log_not_found=$LOG"; exit 2; }

TAIL_LINES="${TAIL_LINES:-2000}"
blk="$(tail -n "${TAIL_LINES}" "$LOG")"

need1="$(echo "$blk" | grep -c "prompt_001_8k\\.wav" || true)"
need2="$(echo "$blk" | grep -c "prompt_002_8k\\.wav" || true)"
need3="$(echo "$blk" | grep -c "prompt_003_8k\\.wav" || true)"
hang="$(echo "$blk" | grep -c "Hangup .*\\[NORMAL_CLEARING\\]" || true)"

bad="$(echo "$blk" | grep -E "FILE NOT FOUND|sample rate 24000|attempt to concatenate a nil|ERROR" -c || true)"

if [[ "$need1" -gt 0 && "$need2" -gt 0 && "$need3" -gt 0 && "$hang" -gt 0 && "$bad" -eq 0 ]]; then
  echo "OK"
  echo "prompt_001=$need1 prompt_002=$need2 prompt_003=$need3 hangup_normal=$hang bad=$bad"
  exit 0
fi

echo "NG"
echo "prompt_001=$need1 prompt_002=$need2 prompt_003=$need3 hangup_normal=$hang bad=$bad"
echo "HINT: tail -n ${TAIL_LINES} ${LOG} | grep -E \"prompt_00[123]_8k\\.wav|Hangup|FILE NOT FOUND|sample rate 24000|attempt to concatenate a nil|ERROR\" | tail -n 120"
exit 2
