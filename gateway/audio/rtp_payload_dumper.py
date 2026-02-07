# -*- coding: utf-8 -*-
"""
RTP受信"直後"（デコード前）のpayloadを/tmpへダンプする診断ユーティリティ。
リアルタイム監視や無限待ちを避けるため、秒数/パケット数で自動停止する。

Env:
  LC_RTP_DUMP=1               enable
  LC_RTP_DUMP_SECONDS=12      stop after N seconds
  LC_RTP_DUMP_MAX_PKTS=0      stop after N pkts (0 = unlimited within seconds)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except Exception:
        return default


def _env_bool(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


@dataclass
class DumpStats:
    pkts: int = 0
    bytes_total: int = 0
    zero_bytes: int = 0
    same_payload_streak_max: int = 0


class RtpPayloadDumper:
    def __init__(self, call_uuid: str = "unknown"):
        self.enabled = _env_bool("LC_RTP_DUMP")
        self.seconds = max(1, _env_int("LC_RTP_DUMP_SECONDS", 12))
        self.max_pkts = max(0, _env_int("LC_RTP_DUMP_MAX_PKTS", 0))
        self.call_uuid = call_uuid or "unknown"

        self._start: Optional[float] = None
        self._end: Optional[float] = None
        self._raw_path: Optional[str] = None
        self._meta_path: Optional[str] = None
        self._rawf = None
        self._metaf = None
        self._closed = False

        self._last_payload: Optional[bytes] = None
        self._same_streak = 0
        self.stats = DumpStats()

    def _open_if_needed(self):
        if not self.enabled or self._start is not None:
            return
        ts = int(time.time())
        outdir = "/tmp"
        self._raw_path = os.path.join(outdir, f"rtp_payload_{self.call_uuid}_{ts}.pcmu")
        self._meta_path = os.path.join(outdir, f"rtp_payload_{self.call_uuid}_{ts}.meta")
        self._rawf = open(self._raw_path, "wb")
        self._metaf = open(self._meta_path, "w", encoding="utf-8")
        self._start = time.time()
        self._end = self._start + float(self.seconds)
        self._metaf.write(f"[rtp_dump] start={self._start:.3f} seconds={self.seconds} max_pkts={self.max_pkts}\n")
        self._metaf.flush()

    def should_stop(self) -> bool:
        if not self.enabled or self._closed or self._start is None or self._end is None:
            return False
        if time.time() >= self._end:
            return True
        if self.max_pkts and self.stats.pkts >= self.max_pkts:
            return True
        return False

    def feed(self, payload: bytes):
        if not self.enabled or self._closed:
            return
        try:
            self._open_if_needed()
            if self._closed or self._rawf is None:
                return

            self.stats.pkts += 1
            self.stats.bytes_total += len(payload)
            self.stats.zero_bytes += payload.count(0)

            if self._last_payload == payload:
                self._same_streak += 1
            else:
                if self._same_streak > self.stats.same_payload_streak_max:
                    self.stats.same_payload_streak_max = self._same_streak
                self._same_streak = 0
                self._last_payload = payload

            self._rawf.write(payload)

            if self.stats.pkts <= 8 and self._metaf:
                hex16 = " ".join(f"{b:02x}" for b in payload[:16])
                self._metaf.write(f"[pkt] n={self.stats.pkts} len={len(payload)} hex16={hex16}\n")
                self._metaf.flush()

            if self.should_stop():
                self.close()
        except Exception:
            # 診断は通話を壊さない
            try:
                self.close()
            except Exception:
                pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._metaf:
                # finalize streak
                if self._same_streak > self.stats.same_payload_streak_max:
                    self.stats.same_payload_streak_max = self._same_streak
                zr = 0.0
                if self.stats.bytes_total > 0:
                    zr = self.stats.zero_bytes / float(self.stats.bytes_total)
                self._metaf.write(f"[summary] pkts={self.stats.pkts} bytes={self.stats.bytes_total} zero_ratio={zr:.6f}\n")
                self._metaf.write(f"[summary] same_payload_streak_max={self.stats.same_payload_streak_max}\n")
                self._metaf.write(f"[files] raw={self._raw_path}\n")
                self._metaf.flush()
        finally:
            try:
                if self._rawf:
                    self._rawf.close()
            finally:
                if self._metaf:
                    self._metaf.close()
