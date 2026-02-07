#!/usr/bin/env python3
"""EVL - ヘルパー関数群（純粋関数のみ、副作用なし）"""
import os
import time
import logging
import traceback

logger = logging.getLogger(__name__)


def _h(ev, *keys, default=None):
    """FreeSWITCHヘッダ取得ヘルパ"""
    for key in keys:
        try:
            value = ev.getHeader(key)
        except Exception:
            value = None
        if value:
            return value
    return default


def _evl_fatal_write(msg: str) -> None:
    _EVL_FATAL_PATH = "/tmp/event_listener.fatal.trace"
    try:
        fd = os.open(_EVL_FATAL_PATH, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
        try:
            os.write(fd, msg.encode("utf-8", "replace"))
        finally:
            os.close(fd)
    except BaseException:
        pass


def _evl_excepthook(exctype, value, tb) -> None:
    _evl_fatal_write(f"[EVL_UNCAUGHT] ts={int(time.time())} pid={os.getpid()} exctype={getattr(exctype,'__name__',exctype)} value={value!r}\n")
    _evl_fatal_write("".join(traceback.format_tb(tb)))
    _evl_fatal_write("[EVL_UNCAUGHT_END]\n")


def _evl_thread_excepthook(args) -> None:
    _evl_fatal_write(f"[EVL_THREAD_UNCAUGHT] ts={int(time.time())} pid={os.getpid()} thread={getattr(args,'thread',None)} exc={args.exc_type} {args.exc_value!r}\n")
    try:
        _evl_fatal_write("".join(traceback.format_tb(args.exc_traceback)))
    except BaseException:
        pass
    _evl_fatal_write("[EVL_THREAD_UNCAUGHT_END]\n")


def _evl_conn(msg: str) -> None:
    try:
        os.write(2, f"{time.time():.3f} [EVL_CONN] {msg}\n".encode())
    except Exception:
        pass


def _evl_conn_trace(exc: BaseException) -> None:
    try:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        os.write(2, trace.encode())
    except Exception:
        pass


def _evl_send(msg: str) -> None:
    try:
        os.write(2, f"{time.time():.3f} [EVL_SEND] {msg}\n".encode())
    except Exception:
        pass


def _log_play_decide(uuid: str, do_play: bool, **details) -> None:
    extras = " ".join(
        f"{key}={value}" for key, value in details.items() if value is not None
    )
    logger.info(
        "[EVL_PLAY_DECIDE] uuid=%s do_play=%d %s",
        uuid,
        1 if do_play else 0,
        extras,
    )
