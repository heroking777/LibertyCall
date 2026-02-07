#!/usr/bin/env python3
import os
os.write(2, b"[EVL_SOCK] TOP_REACHED\n")
"""
FreeSWITCH Event Socket Listener (PyESL版)
通話イベントを常時受信して、gateway処理をトリガーする
"""
import sys
import time
import logging
import socket
import threading
from collections import defaultdict
from pathlib import Path
from typing import Optional

from evl_helpers import (
    _evl_fatal_write, _evl_excepthook, _evl_thread_excepthook,
    _evl_conn, _evl_conn_trace, _h,
)
from evl_esl_state import set_esl_connection
from evl_gateway_sender import (
    send_event_to_gateway, _send_forced_gateway_event,
    _maybe_force_forward, _send_boot_probe,
)
from evl_call_handlers import handle_channel_create, handle_call, handle_hangup

_BOOT_TS = time.time()
_EVL_BUILD = "EVL_BUILD_20260128_2335_A"
try:
    sys.stderr.write(
        f"[EVL_BOOT] ts={_BOOT_TS:.3f} file={__file__} pid={os.getpid()} "
        f"euid={os.geteuid()} cwd={os.getcwd()} py={sys.executable}\n"
    )
    sys.stderr.flush()
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

sys.excepthook = _evl_excepthook
try:
    threading.excepthook = _evl_thread_excepthook
except BaseException:
    pass

_evl_fatal_write(f"[EVL_TOP2] ts={int(time.time())} pid={os.getpid()} file={__file__}\n")

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
from libs.esl.ESL import ESLconnection

try:
    from gateway.core.client_mapper import resolve_client_id
except ImportError:
    resolve_client_id = None


def _connect_event_socket_once(socket_path, timeout=2.0, attempt=None):
    _evl_conn(f"TRY attempt={attempt} path={socket_path} pid={os.getpid()}")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(socket_path))
        _evl_conn(f"OK attempt={attempt} path={socket_path} fd={sock.fileno()}")
        return True
    except Exception as exc:
        _evl_conn(f"FAIL attempt={attempt} path={socket_path} exc={exc!r}")
        _evl_conn_trace(exc)
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _ensure_event_socket_connection(socket_path, max_attempts=30, delay=1.0):
    for attempt in range(1, max_attempts + 1):
        if _connect_event_socket_once(socket_path, attempt=attempt):
            return
        if attempt < max_attempts:
            time.sleep(delay)
    _evl_conn(f"GIVEUP attempts={max_attempts} path={socket_path}")


_EVENT_SOCKET_PATH = Path(
    os.environ.get("LIBERTY_GATEWAY_EVENTS_SOCK", "/tmp/liberty_gateway_events.sock")
)
logger.info("[EVL_CFG] sock_path=%s", _EVENT_SOCKET_PATH)
_ensure_event_socket_connection(_EVENT_SOCKET_PATH)


def main():
    host, port, password = "127.0.0.1", "8021", "ClueCon"
    _send_boot_probe()
    logger.info(f"FreeSWITCH Event Socket に接続中... ({host}:{port})")
    con = ESLconnection(host, port, password)
    connected = int(con.connected())
    logger.info("[EVL_ESL_CONN] connected=%s", connected)
    if not connected:
        logger.error("Event Socket 接続失敗")
        return 1
    try:
        status_text = con.api("status")
        status_str = status_text if isinstance(status_text, str) else str(status_text)
        logger.info("[EVL_ESL_API_STATUS] head=%s", status_str.splitlines()[0] if status_str else "")
    except Exception as api_exc:
        logger.exception("[EVL_ESL_API_STATUS] err=%s", api_exc)
    try:
        con.events("plain", "ALL")
    except Exception as sub_exc:
        logger.exception("[EVL_ESL_SUB] err=%s", sub_exc)
    con.events("plain", "CHANNEL_CREATE CHANNEL_ANSWER CHANNEL_EXECUTE CHANNEL_EXECUTE_COMPLETE CHANNEL_PARK CHANNEL_HANGUP CHANNEL_AUDIO")
    set_esl_connection(con)
    logger.info("Event Socket Listener 起動")

    events_total = 0
    events_window = 0
    events_name_window: dict[str, int] = defaultdict(int)
    window_lock = threading.Lock()
    stop_evt = threading.Event()

    def _esl_rx_logger():
        nonlocal events_total, events_window
        while not stop_evt.wait(1.0):
            with window_lock:
                per_sec = events_window
                total = events_total
                events_window = 0
                top = sorted(events_name_window.items(), key=lambda kv: kv[1], reverse=True)[:3]
                events_name_window.clear()
            top_str = " ".join(f"{n}:{c}" for n, c in top) if top else "none"
            logger.info("[EVL_ESL_RX] per_sec=%s total=%s top=%s", per_sec, total, top_str)

    rx_thread = threading.Thread(target=_esl_rx_logger, daemon=True)
    rx_thread.start()
    active_calls = set()

    try:
        while True:
            try:
                e = con.recvEvent()
                if e is None:
                    continue
                event_name = e.getHeader("Event-Name") or "UNKNOWN"
                uuid = (e.getHeader("Unique-ID") or e.getHeader("Channel-Call-UUID")
                        or e.getHeader("Channel-UUID") or e.getHeader("variable_uuid")
                        or e.getHeader("variable_origination_uuid") or "NONE")
                application = e.getHeader("Application") or "-"
                application_data = e.getHeader("Application-Data") or "-"
                with window_lock:
                    events_total += 1
                    events_window += 1
                    events_name_window[event_name] += 1
                logger.info("[EVL_EVT_IN] type=%s uuid=%s app=%s data=%s",
                           event_name, uuid, application, application_data[:200])
                try:
                    _maybe_force_forward(e)
                except Exception as fe:
                    logger.exception("[EVL_FORCE_ERR] %s", fe)

                dispatched = False
                dispatch_reason = None
                reason_hint = None
                allow_auto = True

                if event_name == "CHANNEL_CREATE":
                    reason_hint = "channel_create"
                    handle_channel_create(uuid, e)
                elif event_name == "CHANNEL_ANSWER":
                    reason_hint = "channel_answer"
                    dest_num = e.getHeader("Caller-Destination-Number")
                    cid = "000"
                    if resolve_client_id:
                        try:
                            cid = resolve_client_id(destination_number=dest_num)
                        except Exception:
                            pass
                    send_event_to_gateway("call_start", uuid, client_id=cid)
                    try:
                        from asr_handler import get_or_create_handler
                        get_or_create_handler(uuid).on_incoming_call()
                    except (ImportError, Exception):
                        pass
                elif event_name == "CHANNEL_EXECUTE":
                    reason_hint = f"channel_execute app={application}"
                    if application == "endless_playback":
                        _send_forced_gateway_event(uuid=uuid, name=event_name,
                            app=application, data=application_data,
                            reason_hint="CHANNEL_EXECUTE app=endless_playback")
                    if application == "playback":
                        if uuid not in active_calls:
                            active_calls.add(uuid)
                            dispatched = True
                            dispatch_reason = "channel_execute_playback"
                            handle_call(uuid, e)
                        else:
                            allow_auto = False
                            dispatch_reason = "channel_execute_playback_duplicate"
                elif event_name == "CHANNEL_EXECUTE_COMPLETE":
                    reason_hint = f"channel_execute_complete app={application}"
                    if application == "playback":
                        if "002.wav" in application_data:
                            try:
                                Path(f"/tmp/asr_enable_{uuid}.flag").touch()
                            except Exception:
                                pass
                        if uuid in active_calls:
                            continue
                        continue
                    elif application == "park":
                        continue
                elif event_name == "CHANNEL_PARK":
                    reason_hint = "channel_park"
                    new_uuid = e.getHeader("Unique-ID")
                    old_uuid = (e.getHeader("Channel-Call-UUID")
                                or e.getHeader("Channel-UUID") or uuid)
                    if new_uuid and new_uuid not in active_calls:
                        active_calls.add(new_uuid)
                        active_calls.add(old_uuid)
                        e.addHeader("Original-UUID", old_uuid)
                        dispatched = True
                        dispatch_reason = "channel_park"
                        handle_call(new_uuid, e)
                    else:
                        allow_auto = False
                        dispatch_reason = "channel_park_duplicate"
                elif event_name == "CHANNEL_HANGUP":
                    reason_hint = "channel_hangup"
                    send_event_to_gateway("call_end", uuid)
                    active_calls.discard(uuid)
                    try:
                        from asr_handler import remove_handler
                        remove_handler(uuid)
                    except (ImportError, Exception):
                        pass
                    handle_hangup(uuid, e)
                elif event_name == "PLAYBACK_START":
                    reason_hint = "playback_start"
                    _send_forced_gateway_event(uuid=uuid, name=event_name,
                        app=application, data=application_data, reason_hint=reason_hint)

                channel_like = (event_name.startswith("CHANNEL_")
                                or event_name.startswith("PLAYBACK_")
                                or event_name.startswith("MEDIA_BUG_"))
                if allow_auto and not dispatched and channel_like:
                    dispatch_reason = reason_hint or f"auto_dispatch_{event_name}"
                    dispatched = True
                    handle_call(uuid, e)
                if not dispatched and dispatch_reason is None:
                    dispatch_reason = reason_hint or "skip_non_channel_event"
                logger.info("[EVL_DISPATCH] uuid=%s type=%s handled=%d reason=%s",
                           uuid, event_name, 1 if dispatched else 0, dispatch_reason)
            except Exception as loop_err:
                logger.warning(f"イベント処理エラー（継続）: {loop_err}")
                logger.exception("[EVL_ESL_ERR] err=%s", loop_err)
                continue
    except KeyboardInterrupt:
        logger.info("Event Socket Listener を終了します")
        return 0
    except Exception as fatal_err:
        logger.error(f"予期しないエラー: {fatal_err}", exc_info=True)
        return 1
    finally:
        con.disconnect()
        set_esl_connection(None)
        stop_evt.set()
        if rx_thread.is_alive():
            rx_thread.join(timeout=1.0)


if __name__ == "__main__":
    import traceback as _tb
    try:
        main()
    except BaseException:
        with open("/tmp/event_listener.trace", "a") as f:
            f.write("\n[EVL_MAIN_FATAL]\n")
            f.write(_tb.format_exc())
            f.write("\n[EVL_MAIN_FATAL_END]\n")
        raise
