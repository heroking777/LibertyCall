#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remove NUL bytes from logs and write clean output."""
import argparse
import os
import sys

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    ap.add_argument("--max-bytes", dest="max_bytes", type=int, default=50 * 1024 * 1024)
    args = ap.parse_args()

    if not os.path.exists(args.in_path):
        print(f"[evl_log_clean] input not found: {args.in_path}", file=sys.stderr)
        return 2

    size = os.stat(args.in_path).st_size
    with open(args.in_path, "rb") as f:
        if size > args.max_bytes:
            f.seek(max(0, size - args.max_bytes))
        raw = f.read()

    cleaned = raw.replace(b"\x00", b"")
    tmp = args.out_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(cleaned)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, args.out_path)

    print(f"[evl_log_clean] wrote: {args.out_path} bytes={len(raw)} -> {len(cleaned)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
