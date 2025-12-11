#!/usr/bin/env python3
"""
LibertyCall MCP ヘルスチェック用スクリプト。

Example:
    ./scripts/check_mcp_health.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8000/health"
TIMEOUT = 3


def main() -> int:
    try:
        with urllib.request.urlopen(URL, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                print(f"[ERROR] health status: {resp.status}")
                return 1
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != "ok":
                print(f"[ERROR] health payload: {data}")
                return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] health check failed: {exc}")
        return 1

    print("[OK] MCP health check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())











