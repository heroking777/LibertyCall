import asyncio
import binascii
import json
import logging
import os
import queue
import socket
import subprocess
import sys
import threading
import urllib.parse
from contextlib import suppress

import websockets

from gateway.core.ai_core import AICore
from gateway.asr.google_asr import GoogleASR
from gateway.audio.audio_utils import ulaw8k_to_pcm16k

LOG_PATH = "/var/log/asr-ws-sink.log"
RATE_LOG_INTERVAL = 1.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)

AF_TEST_TRANSCRIPT = os.getenv("AF_TEST_TRANSCRIPT")
AI_DISABLE_LLM = os.getenv("AI_DISABLE_LLM", "1")
USE_GOOGLE_ASR = os.getenv("AF_USE_GOOGLE_ASR") == "1"

if AI_DISABLE_LLM != "1":
    logging.error("[AF_WS] AI_DISABLE_LLM は常に 1 が必須です（LLM封鎖）。現在: %r", AI_DISABLE_LLM)
    raise SystemExit(1)

_ai_core: AICore | None = None
_ai_core_proxy = None
FS_CLI_PATH = os.getenv("FS_CLI_PATH", "/usr/local/freeswitch/bin/fs_cli")


def _playback_via_fs_cli(call_uuid: str, audio_file: str) -> None:
    if not call_uuid or not audio_file:
        logging.error("[AF_WS] playback callback missing call_uuid/audio_file")
        return
    cmd = [FS_CLI_PATH, "-x", f"uuid_play {call_uuid} {audio_file}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        logging.info(
            "[AF_WS] playback via fs_cli uuid=%s file=%s rc=%s body=%s",
            call_uuid,
            audio_file,
            result.returncode,
            (result.stdout or result.stderr).strip()[:160],
        )
    except FileNotFoundError:
        logging.error("[AF_WS] FS_CLI not found: path=%s", FS_CLI_PATH)
    except Exception:
        logging.exception("[AF_WS] playback via fs_cli failed")


class _AICoreProxy:
    def __init__(self, core: AICore) -> None:
        self._core = core

    def on_transcript(self, call_id: str, text: str, is_final: bool = True, **kwargs):
        if is_final:
            logging.info("[AF_ASR] FINAL uuid=%s text=%r", call_id, text)
        result = self._core.on_transcript(call_id, text, is_final=is_final, **kwargs)
        if is_final:
            logging.info("[AF_INTENT] call_id=%s result=%r", call_id, result)
        return result

    def __getattr__(self, item):
        return getattr(self._core, item)


def _ensure_ai_core_proxy() -> _AICoreProxy:
    global _ai_core, _ai_core_proxy
    if _ai_core is None:
        _ai_core = AICore(init_clients=False)
    if not getattr(_ai_core, "playback_callback", None):
        _ai_core.playback_callback = _playback_via_fs_cli
    if _ai_core_proxy is None or getattr(_ai_core_proxy, "_core", None) is not _ai_core:
        _ai_core_proxy = _AICoreProxy(_ai_core)
    return _ai_core_proxy


def _parse_autoclose_delay():
    raw = os.getenv("AF_AUTOCLOSE_SEC")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logging.warning("[AF_WS] invalid AF_AUTOCLOSE_SEC=%r", raw)
        return None
    return value if value > 0 else None


ESL_HOST = os.getenv("AF_ESL_HOST", "127.0.0.1")
ESL_PORT = int(os.getenv("AF_ESL_PORT", "8021"))
ESL_PASSWORD = os.getenv("AF_ESL_PASSWORD", "ClueCon")
ESL_TIMEOUT = float(os.getenv("AF_ESL_TIMEOUT_SEC", "3"))
UUID_TEST_CMD = os.getenv(
    "AF_WS_UUID_TEST_CMD",
    "uuid_broadcast {uuid} tone_stream://%(1000,0,660) aleg",
)


class EventSocketClient:
    def __init__(self, host, port, password, timeout=3.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout

    async def _read_frame(self, reader):
        headers = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
            if not line:
                raise ConnectionError("esl closed")
            line = line.decode(errors="replace").strip()
            if line == "":
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        body = b""
        length = int(headers.get("content-length", "0") or "0")
        if length > 0:
            body = await asyncio.wait_for(reader.readexactly(length), timeout=self.timeout)
        return headers, body

    async def send_api(self, command):
        reader = writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            await self._read_frame(reader)  # auth/request
            writer.write(f"auth {self.password}\n\n".encode())
            await writer.drain()
            await self._read_frame(reader)  # auth reply
            writer.write(f"api {command}\n\n".encode())
            await writer.drain()
            headers, body = await self._read_frame(reader)
            reply_text = headers.get("reply-text", "").lower()
            success = reply_text.startswith("+ok")
            return success, body.decode(errors="replace")
        except Exception as exc:
            logging.exception("[AF_ESL] send_api failed cmd=%r", command, exc_info=exc)
            return False, str(exc)
        finally:
            if writer:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()


esl_client = EventSocketClient(ESL_HOST, ESL_PORT, ESL_PASSWORD, ESL_TIMEOUT)


def _uuid_from_ws_path(path: str | None) -> str | None:
    """Extract uuid from websocket path/query."""
    try:
        if not path:
            return None
        parsed = urllib.parse.urlparse(path)
        qs = urllib.parse.parse_qs(parsed.query or "")
        if qs.get("uuid"):
            return qs["uuid"][0]
        segments = (parsed.path or "").strip("/").split("/")
        if len(segments) >= 2 and segments[0] in {"u", "uuid"}:
            return segments[1]
    except Exception:
        return None
    return None


async def handler(ws, path=None):
    peer = ws.remote_address
    proto_req = ws.request_headers.get("Sec-WebSocket-Protocol")
    logging.info("[AF_WS] connected peer=%s subprotocol=%s req_proto=%s path=%s", peer, ws.subprotocol, proto_req, getattr(ws, 'path', None))

    total = 0
    binary_frames_total = 0
    binary_bytes_total = 0
    rate_log_task = None
    autoclose_task = None
    binary_lock = asyncio.Lock()
    metadata = None
    ws_path = getattr(ws, "path", None) or path or ""
    target_uuid = _uuid_from_ws_path(ws_path)
    test_cmd_sent = False
    test_transcript_sent = False
    google_asr = None
    connect_logged = False
    prebuf: list[bytes] = []
    PREBUF_LIMIT = 50  # 約16KB分

    def ensure_connect_logged():
        nonlocal connect_logged
        if target_uuid and not connect_logged:
            logging.info("[AF_WS] CONNECT uuid=%s", target_uuid)
            print(f"[AF_WS] CONNECT uuid={target_uuid} path={ws_path}", file=sys.stderr, flush=True)
            connect_logged = True

    print(f"[AF_WS] CONNECT uuid={target_uuid} path={ws_path}", file=sys.stderr, flush=True)

    async def log_binary_rate_loop():
        prev_frames = 0
        prev_bytes = 0
        while True:
            try:
                await asyncio.sleep(RATE_LOG_INTERVAL)
                async with binary_lock:
                    frames_delta = binary_frames_total - prev_frames
                    bytes_delta = binary_bytes_total - prev_bytes
                    prev_frames = binary_frames_total
                    prev_bytes = binary_bytes_total
                    logging.info(
                        "[AF_WS] binary rate interval=%.1fs frames=%d bytes=%d total_frames=%d total_bytes=%d",
                        RATE_LOG_INTERVAL,
                        frames_delta,
                        bytes_delta,
                        binary_frames_total,
                        binary_bytes_total,
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logging.exception("[AF_WS] binary rate logger crashed")

    rate_log_task = asyncio.create_task(log_binary_rate_loop())

    autoclose_delay = _parse_autoclose_delay()

    async def autoclose_after_delay(delay):
        try:
            await asyncio.sleep(delay)
            if ws.closed:
                return
            logging.warning("[AF_WS] auto-closing connection peer=%s delay=%s", peer, delay)
            await ws.close(code=4000, reason="test-close")
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("[AF_WS] auto-close task crashed")

    if autoclose_delay:
        autoclose_task = asyncio.create_task(autoclose_after_delay(autoclose_delay))

    async def run_uuid_test(uuid_val):
        cmd = UUID_TEST_CMD.format(uuid=uuid_val)
        ok, body = await esl_client.send_api(cmd)
        logging.info("[AF_WS] uuid_test cmd=%r ok=%s body=%r", cmd, ok, body[:160])

    def send_test_transcript(uuid_val):
        nonlocal test_transcript_sent
        if test_transcript_sent or not AF_TEST_TRANSCRIPT:
            return
        try:
            global _ai_core
            if _ai_core is None:
                _ai_core = AICore()
            if not getattr(_ai_core, "playback_callback", None):
                _ai_core.playback_callback = _playback_via_fs_cli
            logging.info(
                "[AF_WS] test transcript injection uuid=%s text=%r",
                uuid_val,
                AF_TEST_TRANSCRIPT,
            )
            _ai_core.on_transcript(uuid_val, AF_TEST_TRANSCRIPT, is_final=True)
            test_transcript_sent = True
        except Exception:
            logging.exception("[AF_WS] test transcript injection failed")

    def ensure_google_asr():
        nonlocal google_asr
        if google_asr is None:
            proxy_core = _ensure_ai_core_proxy()
            google_asr = GoogleASR(ai_core=proxy_core)
        return google_asr

    async def process_binary_chunk(chunk: bytes, *, from_prebuf: bool = False):
        nonlocal total
        size = len(chunk)
        total += size
        async with binary_lock:
            nonlocal binary_frames_total, binary_bytes_total
            binary_frames_total += 1
            binary_bytes_total += size
            current_bytes = binary_bytes_total
        tag = " (prebuf)" if from_prebuf else ""
        print(
            f"[AF_WS] RX_BINARY uuid={target_uuid} bytes={size} total={current_bytes}{tag}",
            file=sys.stderr,
            flush=True,
        )
        if total < 2000:
            head = chunk[:16]
            logging.info(
                "[AF_WS] binary len=%d total=%d head16=%s",
                size,
                total,
                binascii.hexlify(head).decode("ascii"),
            )
        elif total % 32000 < size:
            logging.info("[AF_WS] binary total=%d", total)

        if USE_GOOGLE_ASR:
            try:
                pcm16k = ulaw8k_to_pcm16k(chunk)
                asr = ensure_google_asr()
                asr.feed(target_uuid, pcm16k)
            except Exception:
                logging.exception("[AF_ASR] feed failed uuid=%s", target_uuid)

    try:
        async for msg in ws:
            if isinstance(msg, str):
                logging.info("[AF_WS] text len=%d text=%r", len(msg), msg[:200])
                if metadata is None:
                    try:
                        metadata = json.loads(msg)
                        if isinstance(metadata, dict):
                            target_uuid = metadata.get("uuid") or metadata.get("callid")
                            logging.info("[AF_WS] metadata uuid=%s keys=%s", target_uuid, list(metadata.keys()))
                            ensure_connect_logged()
                            if not target_uuid:
                                logging.error("[AF_WS] NO_UUID metadata=%s", metadata)
                        else:
                            metadata = {"raw": metadata}
                    except Exception as exc:
                        logging.warning("[AF_WS] metadata parse failed: %r", exc)
                if msg.strip() == "{}":
                    # await ws.send('{"type":"ready"}')
                    # logging.info("[AF_WS] sent ready")
                    logging.info("[AF_WS] received {} - no response (test mode)")
                if target_uuid and not test_cmd_sent:
                    test_cmd_sent = True
                    asyncio.create_task(run_uuid_test(target_uuid))
                    send_test_transcript(target_uuid)
            else:
                # bytes
                size = len(msg)
                if not target_uuid:
                    if msg[:1] == b"{":
                        try:
                            s = msg.decode("utf-8", errors="replace")
                            metadata = json.loads(s)
                            if isinstance(metadata, dict):
                                target_uuid = metadata.get("uuid") or metadata.get("callid")
                                print(
                                    f"[AF_WS] META_BYTES uuid={target_uuid} raw={s[:200]}",
                                    file=sys.stderr,
                                    flush=True,
                                )
                                ensure_connect_logged()
                                continue
                        except Exception:
                            pass

                    prebuf.append(msg)
                    if len(prebuf) == 1:
                        print(
                            f"ERROR:root:[AF_WS] NO_UUID binary_chunk={len(msg)} bytes head={msg[:16].hex()}",
                            file=sys.stderr,
                            flush=True,
                        )
                    if len(prebuf) > PREBUF_LIMIT:
                        prebuf.pop(0)
                    continue

                ensure_connect_logged()

                if prebuf:
                    for buffered in prebuf:
                        await process_binary_chunk(buffered, from_prebuf=True)
                    prebuf.clear()

                await process_binary_chunk(msg)
        # no await needed here; rate logger task handles periodic output
    except Exception as exc:
        logging.exception("[AF_WS] handler crashed", exc_info=True)
        try:
            logging.warning(
                "[AF_WS_CLOSE] code=%s reason=%s rcvd=%s sent=%s",
                getattr(ws, 'close_code', None),
                getattr(ws, 'close_reason', None),
                getattr(exc, 'rcvd', None),
                getattr(exc, 'sent', None),
            )
        except Exception:
            logging.warning("[AF_WS_CLOSE] handler error during logging")
    finally:
        for task in (autoclose_task, rate_log_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if target_uuid is not None:
            print(f"[AF_ASR] EOS uuid={target_uuid}", file=sys.stderr, flush=True)
        if USE_GOOGLE_ASR and google_asr and target_uuid:
            try:
                google_asr.end_stream(target_uuid)
            except Exception:
                logging.exception("[AF_ASR] end_stream failed uuid=%s", target_uuid)
        close_code = getattr(ws, "close_code", None)
        close_reason = getattr(ws, "close_reason", None)
        async with binary_lock:
            logging.info(
                "[AF_WS] disconnect peer=%s close_code=%s close_reason=%s binary_frames=%d binary_bytes=%d",
                peer,
                close_code,
                close_reason,
                binary_frames_total,
                binary_bytes_total,
            )
            print(
                f"[AF_WS] CLOSE uuid={target_uuid or 'UNKNOWN'} total_bytes={binary_bytes_total} total_frames={binary_frames_total}",
                file=sys.stderr,
                flush=True,
            )

async def main():
    env_host = os.getenv("AF_WS_HOST")
    env_port = os.getenv("AF_WS_PORT")
    print(
        f"[AF_WS] ENV_HOSTPORT host={env_host} port={env_port}",
        file=sys.stderr,
        flush=True,
    )

    host = "127.0.0.1"
    port = 9000
    logging.info("[AF_WS] starting ws://%s:%d/", host, port)
    print(
        f"[AF_WS] EFFECTIVE_BIND host={host} port={port}",
        file=sys.stderr,
        flush=True,
    )

    try:
        family = socket.AF_INET if host and ":" not in str(host) else socket.AF_UNSPEC
        async with websockets.serve(
            handler,
            host,
            port,
            # subprotocols=["audiostream.drachtio.org"],  # ←FSが送れないので無効化
            max_size=None,
            ping_interval=None,
            family=family,
        ):
            logging.info("[AF_WS] ready")
            await asyncio.Future()
    except OSError as exc:
        print(
            f"[AF_WS] BIND_FAILED host={host} port={port} exc={exc}",
            file=sys.stderr,
            flush=True,
        )
        logging.exception("[AF_WS] bind failed", exc_info=exc)
        raise

if __name__ == "__main__":
    asyncio.run(main())
