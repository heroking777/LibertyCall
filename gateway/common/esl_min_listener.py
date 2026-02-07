#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
esl_min_listener.py

目的:
 - FreeSWITCH Event Socket(8021)への接続可否を切り分ける最小リスナー。
 - 追加機能: SOFIA SIP本体が通常ログに出ない環境向けに、ESL経由で
   Event-Subclass=SOFIA::SIP (or SOFIA::sip) を短時間だけファイル回収する。

重要:
 - stderr出力禁止。/tmp 配下への file-FD 出力のみ。
 - 待機無限禁止。必ず秒数で終了。
 - 指示外の挙動変更禁止（LC_ESL_CAPTURE=1 のときのみ新挙動）。
"""

import os
import socket
import time
from typing import Optional


TRACE_DEFAULT = "/tmp/event_listener.trace"


def _now() -> str:
    try:
        return str(time.time())
    except Exception:
        return "0"


def _write_line(fd: int, msg: str) -> None:
    os.write(fd, (msg + "\n").encode("utf-8", errors="replace"))


def _recv_until(sock: socket.socket, marker: bytes, timeout_s: float = 2.0) -> bytes:
    sock.settimeout(timeout_s)
    buf = b""
    while marker not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        if len(buf) > 2_000_000:
            break
    return buf


def _recv_exact(sock: socket.socket, n: int, timeout_s: float = 2.0) -> bytes:
    sock.settimeout(timeout_s)
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
        if len(buf) > 5_000_000:
            break
    return buf


def _send_cmd(sock: socket.socket, cmd: str) -> None:
    if not cmd.endswith("\n\n"):
        cmd = cmd.rstrip("\n") + "\n\n"
    sock.sendall(cmd.encode("utf-8"))


def _parse_headers(raw: str) -> dict:
    h = {}
    for line in raw.splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            h[k.strip()] = v.strip()
    return h


def _read_esl_frame(sock: socket.socket, timeout_s: float = 2.0) -> bytes:
    """
    ESL frame:
      headers terminated by \\n\\n
      optional body with Content-Length bytes
    """
    head = _recv_until(sock, b"\n\n", timeout_s)
    if not head:
        return b""
    try:
        txt = head.decode("utf-8", errors="replace")
        headers = _parse_headers(txt)
        cl = headers.get("Content-Length")
        if cl is None:
            return head
        n = int(cl)
        if n <= 0:
            return head
        body = _recv_exact(sock, n, timeout_s)
        return head + body
    except Exception:
        return head


def main() -> int:
    # ---- config ----
    host = os.environ.get("LC_ESL_HOST", "127.0.0.1")
    port = int(os.environ.get("LC_ESL_PORT", "8021"))
    password = os.environ.get("LC_ESL_PASSWORD", "ClueCon")

    trace_path = os.environ.get("LC_ESL_TRACE", TRACE_DEFAULT)
    capture = os.environ.get("LC_ESL_CAPTURE", "0") == "1"
    seconds = int(os.environ.get("LC_ESL_SECONDS", "12"))
    want_subclass = os.environ.get("LC_ESL_FILTER_EVENT_SUBCLASS", "SOFIA::SIP")
    # まずは確実に出るイベントを購読して「イベントが流れる」ことを証明する
    event_list = os.environ.get(
        "LC_ESL_EVENTS",
        "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_HANGUP_COMPLETE"
    )

    # ---- open trace fd ----
    fd = os.open(trace_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    _write_line(fd, f"{_now()} [esl_min_listener] start capture={capture} seconds={seconds} want_subclass={want_subclass} events={event_list}")

    # ---- connect ----
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect((host, port))
    except Exception as e:
        _write_line(fd, f"{_now()} [esl_min_listener] connect_error: {e!r}")
        os.close(fd)
        return 2

    # banner
    try:
        banner = _read_esl_frame(s, 2.0)
        _write_line(fd, f"{_now()} [esl_min_listener] banner_len={len(banner)}")
    except Exception as e:
        _write_line(fd, f"{_now()} [esl_min_listener] banner_error: {e!r}")

    # auth
    _send_cmd(s, f"auth {password}")
    try:
        auth_resp = _read_esl_frame(s, 2.0)
        _write_line(fd, f"{_now()} [esl_min_listener] auth_resp={auth_resp[:120]!r}")
    except Exception as e:
        _write_line(fd, f"{_now()} [esl_min_listener] auth_error: {e!r}")

    if not capture:
        _write_line(fd, f"{_now()} [esl_min_listener] capture_disabled exit")
        try:
            s.close()
        except Exception:
            pass
        os.close(fd)
        return 0

    # ---- capture mode ----
    out_path = f"/tmp/esl_capture_{int(time.time())}.log"
    out_fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    _write_line(fd, f"{_now()} [esl_min_listener] capture_out={out_path}")

    # subscribe events (plain) with command variants (some FS builds behave differently)
    # IMPORTANT: do not assume +OK means it actually subscribed.
    cmds = [
        ("linger", "linger"),
        ("events_all", "events plain ALL"),
        ("event_all", "event plain ALL"),
        ("myevents_plain", "myevents plain"),
        ("event_list", f"event plain {event_list}"),
    ]
    for tag, cmd in cmds:
        _send_cmd(s, cmd)
        r = _read_esl_frame(s, 2.0)
        _write_line(fd, f"{_now()} [esl_min_listener] resp_{tag}={r[:120]!r}")

    deadline = time.time() + max(1, seconds)
    s.settimeout(1.0)
    matched = 0
    total = 0
    raw_first: Optional[bytes] = None
    buf = b""

    # NOTE:
    # - ESL frames may include Content-Length body; we only need to prove "any data arrives".
    # - So we treat ANY received chunk as evidence and keep raw_first_hex.
    while time.time() < deadline:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            if raw_first is None:
                raw_first = chunk[:200]
            buf += chunk
            # event boundary
            while b"\n\n" in buf:
                part, buf = buf.split(b"\n\n", 1)
                total += 1
                txt = part.decode("utf-8", errors="replace")
                headers = _parse_headers(txt)
                subclass = headers.get("Event-Subclass") or headers.get("Event-Subclass:")
                # まずはイベントが流れていることを証明するため全ヘッダを保存（上限あり）
                _write_line(out_fd, "----- EVENT HEADER BEGIN -----")
                os.write(out_fd, (txt + "\n").encode("utf-8", errors="replace"))
                _write_line(out_fd, "----- EVENT HEADER END -----")

                if subclass and want_subclass.lower() in subclass.lower():
                    matched += 1
        except socket.timeout:
            continue
        except Exception as e:
            _write_line(fd, f"{_now()} [esl_min_listener] recv_error: {e!r}")
            break

    if total == 0:
        if raw_first is None:
            _write_line(fd, f"{_now()} [esl_min_listener] no_events raw_first=None")
        else:
            hx = raw_first.hex()
            _write_line(fd, f"{_now()} [esl_min_listener] no_events raw_first_hex={hx}")

    _write_line(fd, f"{_now()} [esl_min_listener] capture_done total={total} matched={matched} out={out_path}")
    try:
        s.close()
    except Exception:
        pass
    os.close(out_fd)
    os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
