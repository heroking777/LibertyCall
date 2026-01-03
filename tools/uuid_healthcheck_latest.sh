#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

pick_latest() {
  ls -1t /tmp/call_uuid_*.txt 2>/dev/null \
    | grep -v -E 'FAKE|TEST|badcallid|badext' \
    | head -n 1 || true
}

f="$(pick_latest)"
[[ -n "$f" && -f "$f" ]] || { echo "NG: no call_uuid file found"; exit 2; }

echo "FILE=$f"

bash "${BASE_DIR}/check_uuid_outfile_contract.sh" "$f"
bash "${BASE_DIR}/inspect_uuid_outfile.sh" "$f"
