#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTP(PCMU想定)の受信直後のペイロードを保存し、PCMU->PCM(WAV 8k)へ即時ダンプする診断ツール。
目的: 「雑音/無音」の発生地点が FreeSWITCH側か Gateway側か を最短で切り分ける。

NOTE:
- ここではRTPヘッダは最小限パースし、payloadを取り出す（拡張/CSRCは簡易対応）。
- 依存追加禁止。標準ライブラリのみ。
"""

import argparse
import audioop
import os
import socket
import struct
import sys
import time
import wave


def _parse_rtp_payload(packet: bytes):
    """
    Returns: (seq, ts, pt, payload) or (None, None, None, None) if invalid.
    """
    if len(packet) < 12:
        return None, None, None, None
    b0 = packet[0]
    v = (b0 >> 6) & 0x03
    if v != 2:
        return None, None, None, None
    cc = b0 & 0x0F
    x = (b0 >> 4) & 0x01
    b1 = packet[1]
    pt = b1 & 0x7F
    seq = struct.unpack("!H", packet[2:4])[0]
    ts = struct.unpack("!I", packet[4:8])[0]

    header_len = 12 + cc * 4
    if len(packet) < header_len:
        return None, None, None, None

    # extension header
    if x:
        if len(packet) < header_len + 4:
            return None, None, None, None
        ext_len_words = struct.unpack("!H", packet[header_len + 2:header_len + 4])[0]
        header_len += 4 + ext_len_words * 4
        if len(packet) < header_len:
            return None, None, None, None

    payload = packet[header_len:]
    return seq, ts, pt, payload


def _hexdump(b: bytes, n: int = 32) -> str:
    return " ".join(f"{x:02x}" for x in b[:n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7002)
    ap.add_argument("--outdir", default="/tmp/rtp_capture_debug")
    ap.add_argument("--seconds", type=int, default=12, help="capture duration")
    ap.add_argument("--max_packets", type=int, default=0, help="0 means unlimited within seconds")
    ap.add_argument("--expect_pt", type=int, default=0, help="0=PCMU. if set, warn when different")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    raw_path = os.path.join(args.outdir, "payload.raw")
    meta_path = os.path.join(args.outdir, "meta.log")
    wav8_path = os.path.join(args.outdir, "payload_8k.wav")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    sock.settimeout(0.2)

    # WAV (8kHz mono, 16-bit)
    wf = wave.open(wav8_path, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(8000)

    start = time.time()
    end = start + args.seconds
    packets = 0
    bad = 0
    pt_mismatch = 0
    payload_bytes = 0
    zero_bytes = 0
    same_payload_streak_max = 0
    same_payload_streak = 0
    last_payload = None
    sizes = {}

    with open(raw_path, "wb") as rawf, open(meta_path, "w", encoding="utf-8") as mf:
        mf.write(f"[rtp_capture_debug] start={start:.3f} bind={args.bind}:{args.port} seconds={args.seconds}\n")
        mf.flush()

        while time.time() < end:
            if args.max_packets and packets >= args.max_packets:
                break
            try:
                packet, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            seq, ts, pt, payload = _parse_rtp_payload(packet)
            if payload is None:
                bad += 1
                continue

            packets += 1
            sizes[len(payload)] = sizes.get(len(payload), 0) + 1
            payload_bytes += len(payload)
            zero_bytes += payload.count(0)

            if args.expect_pt is not None and pt != args.expect_pt:
                pt_mismatch += 1

            # streak (identical payload = suspicious silence/noise pattern)
            if last_payload == payload:
                same_payload_streak += 1
            else:
                same_payload_streak_max = max(same_payload_streak_max, same_payload_streak)
                same_payload_streak = 0
                last_payload = payload

            # write raw payload (no RTP header)
            rawf.write(payload)

            # decode PCMU -> PCM16 (assume PT=0)
            try:
                pcm = audioop.ulaw2lin(payload, 2)
                wf.writeframes(pcm)
            except Exception as e:
                mf.write(f"[decode_error] seq={seq} ts={ts} err={repr(e)} payload_hex={_hexdump(payload)}\n")
                mf.flush()

            if packets <= 10:
                mf.write(
                    f"[pkt] n={packets} from={addr[0]}:{addr[1]} seq={seq} ts={ts} pt={pt} "
                    f"payload_len={len(payload)} payload_hex={_hexdump(payload)}\n"
                )
                mf.flush()

        same_payload_streak_max = max(same_payload_streak_max, same_payload_streak)

        # summary
        mf.write(f"[summary] packets={packets} bad={bad} pt_mismatch={pt_mismatch}\n")
        mf.write(f"[summary] payload_bytes={payload_bytes} zero_ratio={(zero_bytes / max(1,payload_bytes)):.6f}\n")
        mf.write(f"[summary] same_payload_streak_max={same_payload_streak_max}\n")
        mf.write(f"[summary] payload_size_hist={dict(sorted(sizes.items()))}\n")

    wf.close()
    sock.close()

    print(f"OK: outdir={args.outdir}")
    print(f" - {meta_path}")
    print(f" - {raw_path}")
    print(f" - {wav8_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
