#!/usr/bin/env python3
"""EVL - ゲートウェイイベント送信（Unixソケット経由）"""
import json
import os
import socket
import time
import logging
import traceback
from pathlib import Path
from typing import Optional

from evl_helpers import _h, _evl_conn, _evl_conn_trace, _evl_send

logger = logging.getLogger(__name__)

_EVENT_SOCKET_PATH = Path(
    os.environ.get("LIBERTY_GATEWAY_EVENTS_SOCK", "/tmp/liberty_gateway_events.sock")
)
_GW_SOCKET_PATH = _EVENT_SOCKET_PATH
_GW_SOCK: Optional[socket.socket] = None


def _gw_connect(timeout: float = 1.0) -> socket.socket:
    global _GW_SOCK
    if _GW_SOCK is not None:
        return _GW_SOCK
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        st = os.stat(_GW_SOCKET_PATH)
        real_path = os.path.realpath(_GW_SOCKET_PATH)
        _evl_conn(
            f"[EVL_SOCK] STAT path={_GW_SOCKET_PATH} real={real_path} ino={st.st_ino} pid={os.getpid()}"
        )
    except Exception as stat_exc:
        _evl_conn(f"[EVL_SOCK] STAT_FAIL path={_GW_SOCKET_PATH} err={stat_exc!r}")
    _evl_conn(f"[EVL_SOCK] CONNECT_TRY path={_GW_SOCKET_PATH} pid={os.getpid()}")
    sock.connect(str(_GW_SOCKET_PATH))
    try:
        sockname = sock.getsockname()
    except OSError:
        sockname = "?"
    try:
        peername = sock.getpeername()
    except OSError:
        peername = "?"
    _evl_conn(
        f"[EVL_SOCK] CONNECT_OK path={_GW_SOCKET_PATH} fd={sock.fileno()} sockname={sockname} peer={peername}"
    )
    _GW_SOCK = sock
    return sock


def _gw_close(reason: str) -> None:
    global _GW_SOCK
    if _GW_SOCK is None:
        return
    try:
        _evl_conn(f"CLOSE reason={reason}")
        _GW_SOCK.close()
    except Exception:
        pass
    finally:
        _GW_SOCK = None


def _gw_recv_line(sock: socket.socket, timeout: float = 1.0) -> bytes:
    sock.settimeout(timeout)
    data = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionResetError("recv EOF")
        data += chunk
        newline_idx = data.find(b"\n")
        if newline_idx != -1:
            return data[: newline_idx + 1]


def send_event_to_gateway(
    event_type: str,
    uuid: str,
    call_id: Optional[str] = None,
    client_id: str = "000",
    extra_payload: Optional[dict] = None,
) -> bool:
    """realtime_gatewayにイベントを送信（Unixソケット経由）"""
    socket_path = _GW_SOCKET_PATH
    if not socket_path.exists():
        logger.warning(f"[EVENT_SOCKET] Socket file not found: {socket_path}")
        return False
    message = {
        "event": event_type,
        "uuid": uuid,
        "call_id": call_id,
        "client_id": client_id,
    }
    if extra_payload:
        message.update(extra_payload)
    payload = json.dumps(message).encode("utf-8")
    line = payload.rstrip(b"\n") + b"\n"
    for attempt in range(2):
        try:
            sock = _gw_connect()
            _evl_send(f"TRY bytes={len(line)} event={event_type} uuid={uuid} attempt={attempt}")
            _evl_conn(f"[EVL_SOCK] SEND bytes={len(line)} event={event_type} uuid={uuid} attempt={attempt}")
            sock.sendall(line)
            resp = _gw_recv_line(sock)
            _evl_conn(f"[EVL_SOCK] RESP event={event_type} uuid={uuid} line={resp[:200]!r}")
            _evl_send(f"RESP line={resp[:200]!r}")
            resp_line = resp.decode("utf-8", "replace").strip()
            if resp_line != "OK":
                logger.warning("[EVENT_SOCKET] Unexpected response from gateway: %s", resp_line)
            else:
                logger.info(f"[EVENT_SOCKET] Event sent successfully: {event_type} uuid={uuid} call_id={call_id}")
            return True
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError) as exc:
            _evl_conn(f"RECONNECT attempt={attempt} event={event_type} uuid={uuid} err={exc!r}")
            _gw_close("send_failed")
        except Exception as e:
            errno_val = getattr(e, "errno", None)
            logger.error(
                "[EVL_BIND_FAIL] path=%s event=%s uuid=%s errno=%s msg=%s",
                socket_path, event_type, uuid, errno_val, e, exc_info=True,
            )
            _evl_conn(f"FAIL event={event_type} uuid={uuid} path={socket_path} errno={errno_val} exc={e!r}")
            try:
                trace = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                os.write(2, trace.encode())
            except Exception:
                pass
            _gw_close("fatal")
            return False
    logger.error(f"[EVENT_SOCKET] send_event_to_gateway exhausted retries event={event_type} uuid={uuid}")
    return False


_FORCED_SENT: dict[str, int] = {}


def _send_forced_gateway_event(
    uuid: str, name: str, app: Optional[str], data: Optional[str],
    reason_hint: Optional[str] = None,
) -> None:
    extra_payload = {"name": name, "app": app or "-", "data": (data or "-")[:400]}
    logger.info(
        "[EVL_SOCK_FORCE] uuid=%s payload_event=fs_evt name=%s app=%s data=%s hint=%s",
        uuid, name, app, (data or "-")[:200], reason_hint,
    )
    ok = send_event_to_gateway("fs_evt", uuid, extra_payload=extra_payload)
    if not ok:
        logger.warning("[EVL_SOCK_FORCE] send_event_to_gateway failed for uuid=%s type=%s", uuid, name)


def _maybe_force_forward(ev) -> bool:
    name = _h(ev, "Event-Name", default="UNKNOWN") or "UNKNOWN"
    uuid = _h(ev, "Unique-ID", "Channel-Call-UUID", "Channel-UUID",
              "variable_uuid", "variable_origination_uuid", default=None)
    app = _h(ev, "Application", "Application-Name", default="-") or "-"
    data = _h(ev, "Application-Data", "Application-Arguments", default="-") or "-"
    logger.info("[EVL_FORCE_SEEN] uuid=%s name=%s app=%s data=%s", uuid or "NONE", name, app, (data or "-")[:200])
    if not uuid:
        logger.info("[EVL_FORCE_SKIP] uuid=%s name=%s reason=%s", uuid, name, "no_uuid")
        return False
    is_trigger = False
    reason = ""
    if name == "CHANNEL_EXECUTE" and app in ("endless_playback", "playback", "uuid_broadcast"):
        is_trigger = True
        reason = f"CHANNEL_EXECUTE app={app}"
    elif name.startswith("PLAYBACK_"):
        is_trigger = True
        reason = name
    elif name in ("MEDIA_BUG_START", "MEDIA_BUG_STOP"):
        is_trigger = True
        reason = name
    if not is_trigger:
        logger.info("[EVL_FORCE_SKIP] uuid=%s name=%s reason=%s", uuid, name, "not_target_event")
        return False
    key = f"{uuid}:{reason}"
    if _FORCED_SENT.get(key):
        logger.info("[EVL_FORCE_SKIP] uuid=%s name=%s reason=%s", uuid, name, "already_sent")
        return False
    _FORCED_SENT[key] = 1
    logger.info("[EVL_FORCE_MATCH] uuid=%s name=%s app=%s data=%s reason=%s", uuid, name, app, data, reason)
    _send_forced_gateway_event(uuid=uuid, name=name, app=app, data=data, reason_hint=reason)
    return True


def _send_boot_probe() -> None:
    probe_uuid = "boot_probe"
    try:
        ok = send_event_to_gateway(
            "probe", probe_uuid, call_id=probe_uuid, client_id="000",
            extra_payload={"ts": time.time()},
        )
        if ok:
            logger.info("[EVL_SOCK] BOOT_PROBE_SENT uuid=%s", probe_uuid)
        else:
            logger.warning("[EVL_SOCK] BOOT_PROBE_RESP_NG uuid=%s", probe_uuid)
    except Exception as exc:
        logger.exception("[EVL_SOCK] BOOT_PROBE_FAIL uuid=%s err=%s", probe_uuid, exc)
