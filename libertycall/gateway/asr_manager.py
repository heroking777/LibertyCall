"""ASR handlers shared between AICore and realtime gateway."""

from __future__ import annotations

import asyncio
import audioop
import os
import socket
import subprocess
import threading
import time
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from libertycall.client_loader import load_client_profile
from libertycall.console_bridge import console_bridge
from libertycall.gateway.audio_utils import pcm24k_to_ulaw8k
from libertycall.gateway.text_utils import normalize_text
from libertycall.gateway.transcript_normalizer import normalize_transcript

from .google_asr import GoogleASR
import numpy as np
from scipy.signal import resample_poly

try:  # pragma: no cover - optional dependency
    from scapy.all import IP, UDP, sniff

    SCAPY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SCAPY_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


# Google Streaming ASR統合
try:
    from asr_handler import get_or_create_handler, remove_handler, get_handler

    ASR_HANDLER_AVAILABLE = True
except ImportError:
    ASR_HANDLER_AVAILABLE = False
    get_or_create_handler = None
    remove_handler = None
    get_handler = None

# ★ 転送先電話番号 (デフォルト)
OPERATOR_NUMBER = "08024152649"


@dataclass
class DialogueResult:
    call_id: str
    user_audio: bytes
    text_raw: Optional[str]
    intent: Optional[str]
    reply_text: Optional[str]
    tts_audio_24k: Optional[bytes]
    should_transfer: bool
    rms_avg: float
    duration_sec: float


@dataclass
class ASRProcessResult:
    dialogue: Optional[DialogueResult] = None
    barge_in_triggered: bool = False
    reset_no_input_timer: bool = False


@dataclass
class CallAudioState:
    audio_buffer: bytearray = field(default_factory=bytearray)
    turn_rms_values: List[int] = field(default_factory=list)
    is_user_speaking: bool = False
    current_segment_start: Optional[float] = None
    last_voice_wall: float = field(default_factory=time.time)
    last_voice_mono: float = field(default_factory=time.monotonic)
    last_silence_mono: Optional[float] = None
    backchannel_sent: bool = False
    stream_chunk_counter: int = 0
    last_feed_time: float = field(default_factory=time.time)


def init_asr(core) -> None:
    asr_provider = os.getenv("LC_ASR_PROVIDER", "google").lower()
    if asr_provider not in ["google", "whisper"]:
        raise ValueError(
            f"未知のASRプロバイダ: {asr_provider}\n"
            "有効な値: 'google' または 'whisper'\n"
            "（'local' はサポートされていません。'whisper' を使用してください。）"
        )

    core.asr_provider = asr_provider
    core.logger.info("AICore: ASR provider = %s", asr_provider)

    core.streaming_enabled = os.getenv("LC_ASR_STREAMING_ENABLED", "0") == "1"

    if core.init_clients:
        if asr_provider == "google":
            phrase_hints = core._load_phrase_hints()
            try:
                core.asr_model = GoogleASR(
                    language_code="ja",
                    sample_rate=16000,
                    phrase_hints=phrase_hints,
                    ai_core=core,
                    error_callback=core._on_asr_error,
                )
                core.logger.info("AICore: GoogleASR を初期化しました")
                core._phrase_hints = phrase_hints
            except Exception as exc:
                error_msg = str(exc)
                if "was not found" in error_msg or "credentials" in error_msg.lower():
                    core.logger.error(
                        "AICore: GoogleASR の初期化に失敗しました（認証エラー）: %s\n"
                        "環境変数 LC_GOOGLE_PROJECT_ID と LC_GOOGLE_CREDENTIALS_PATH を確認してください。\n"
                        "ASR機能は無効化されますが、GatewayはRTP受信を継続します。",
                        error_msg,
                    )
                else:
                    core.logger.error(
                        "AICore: GoogleASR の初期化に失敗しました: %s\n"
                        "ASR機能は無効化されますが、GatewayはRTP受信を継続します。",
                        error_msg,
                    )
                core.asr_model = None
                core.logger.warning("AICore: ASR機能なしでGatewayを起動します（RTP受信は継続されます）")
        elif asr_provider == "whisper":
            from libertycall.asr.whisper_local import WhisperLocalASR  # type: ignore[import-untyped]

            core.logger.debug("AICore: Loading Whisper via WhisperLocalASR...")
            core.asr_model = WhisperLocalASR(
                model_name="base",
                input_sample_rate=16000,
                language="ja",
                device="cpu",
                compute_type="int8",
                temperature=0.0,
                vad_filter=False,
                vad_parameters=None,
            )
            core.logger.info("AICore: WhisperLocalASR を初期化しました")

        if core.streaming_enabled:
            core.logger.info("AICore: ストリーミングASRモード有効")

        core._init_tts()
        core.logger.info(
            "ASR_BOOT: provider=%s streaming_enabled=%s",
            asr_provider,
            core.streaming_enabled,
        )
    else:
        core.logger.info(
            "AICore: init_clients=False のため ASR/TTS 初期化をスキップします (simulation mode)"
        )


def on_new_audio(core, call_id: str, pcm16k_bytes: bytes) -> None:
    core.logger.debug(
        "[AI_CORE] on_new_audio called. Len=%s call_id=%s",
        len(pcm16k_bytes),
        call_id,
    )

    if not core.streaming_enabled:
        return

    if call_id not in core._call_started_calls:
        core.logger.warning(
            "[ASR_RECOVERY] call_id=%s not in _call_started_calls but receiving audio. Auto-registering.",
            call_id,
        )
        core._call_started_calls.add(call_id)

    if core.asr_provider == "google":
        core.logger.debug(
            "AICore: on_new_audio (provider=google) call_id=%s len=%s bytes",
            call_id,
            len(pcm16k_bytes),
        )

        if not hasattr(core, "asr_instances"):
            core.asr_instances = {}
            core.asr_lock = threading.Lock()
            core._phrase_hints = []
            print("[ASR_INSTANCES_LAZY_INIT] asr_instances and lock created (lazy)", flush=True)

        asr_instance = None
        newly_created = False
        with core.asr_lock:
            print(
                f"[ASR_LOCK_ACQUIRED] call_id={call_id}, current_instances={list(core.asr_instances.keys())}",
                flush=True,
            )

            if call_id not in core.asr_instances:
                caller_stack = traceback.extract_stack()
                caller_info = f"{caller_stack[-3].filename}:{caller_stack[-3].lineno} in {caller_stack[-3].name}"
                print(f"[ASR_INSTANCE_CREATE] Creating new GoogleASR for call_id={call_id}", flush=True)
                print(f"[ASR_CREATE_CALLER] call_id={call_id}, caller={caller_info}", flush=True)
                core.logger.info("[ASR_INSTANCE_CREATE] Creating new GoogleASR for call_id=%s", call_id)
                try:
                    new_asr = GoogleASR(
                        language_code="ja",
                        sample_rate=16000,
                        phrase_hints=getattr(core, "_phrase_hints", []),
                        ai_core=core,
                        error_callback=core._on_asr_error,
                    )
                    core.asr_instances[call_id] = new_asr
                    newly_created = True
                    print(
                        f"[ASR_INSTANCE_CREATED] call_id={call_id}, total_instances={len(core.asr_instances)}",
                        flush=True,
                    )
                    core.logger.info(
                        "[ASR_INSTANCE_CREATED] call_id=%s, total_instances=%s",
                        call_id,
                        len(core.asr_instances),
                    )
                except Exception as exc:
                    core.logger.error(
                        "[ASR_INSTANCE_CREATE_FAILED] call_id=%s: %s",
                        call_id,
                        exc,
                        exc_info=True,
                    )
                    print(f"[ASR_INSTANCE_CREATE_FAILED] call_id={call_id}: {exc}", flush=True)
                    return
            else:
                print(f"[ASR_INSTANCE_REUSE] call_id={call_id} already exists", flush=True)

            asr_instance = core.asr_instances.get(call_id)

        if newly_created and asr_instance is not None:
            asr_instance._start_stream_worker(call_id)
            max_wait = 0.5
            wait_interval = 0.02
            elapsed = 0.0
            print(
                f"[ASR_STREAM_WAIT] call_id={call_id} Waiting for stream thread to start...",
                flush=True,
            )
            while elapsed < max_wait:
                if asr_instance._stream_thread is not None and asr_instance._stream_thread.is_alive():
                    break
                time.sleep(wait_interval)
                elapsed += wait_interval

            stream_ready = (
                asr_instance._stream_thread is not None and asr_instance._stream_thread.is_alive()
            )
            if stream_ready:
                print(
                    f"[ASR_STREAM_READY] call_id={call_id} Stream thread ready after {elapsed:.3f}s",
                    flush=True,
                )
                core.logger.info(
                    "[ASR_STREAM_READY] call_id=%s Stream thread ready after %.3fs",
                    call_id,
                    elapsed,
                )
            else:
                print(
                    f"[ASR_STREAM_TIMEOUT] call_id={call_id} Stream thread not ready after {elapsed:.3f}s",
                    flush=True,
                )
                core.logger.warning(
                    "[ASR_STREAM_TIMEOUT] call_id=%s Stream thread not ready after %.3fs",
                    call_id,
                    elapsed,
                )

        if asr_instance is not None:
            try:
                core.logger.warning(
                    "[ON_NEW_AUDIO_FEED] About to call feed_audio for call_id=%s, chunk_size=%s",
                    call_id,
                    len(pcm16k_bytes),
                )
                asr_instance.feed_audio(call_id, pcm16k_bytes)
                core.logger.warning(
                    "[ON_NEW_AUDIO_FEED_DONE] feed_audio completed for call_id=%s",
                    call_id,
                )
            except Exception as exc:
                core.logger.error(
                    "AICore: GoogleASR.feed_audio 失敗 (call_id=%s): %s",
                    call_id,
                    exc,
                    exc_info=True,
                )
                core.logger.info(
                    "ASR_GOOGLE_ERROR: feed_audio失敗 (call_id=%s): %s",
                    call_id,
                    exc,
                )
    else:
        core.asr_model.feed(call_id, pcm16k_bytes)  # type: ignore[union-attr]


class ESLAudioReceiver:
    """Receive decoded audio frames from FreeSWITCH via ESL."""

    def __init__(self, call_id: str, uuid: str, gateway: "RealtimeGateway", logger):
        self.call_id = call_id
        self.uuid = uuid
        self.gateway = gateway
        self.logger = logger
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.conn = None

    def start(self) -> None:
        """Begin ESL event consumption in a background thread."""

        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        self.logger.info(
            "[ESL_AUDIO] Started for call_id=%s, uuid=%s", self.call_id, self.uuid
        )

    def _receive_loop(self) -> None:
        try:
            from libs.esl.ESL import ESLconnection

            self.conn = ESLconnection("127.0.0.1", "8021", "ClueCon")

            if not self.conn.connected():
                self.logger.error("[ESL_AUDIO] Failed to connect to FreeSWITCH ESL")
                return

            self.conn.events("plain", "CHANNEL_AUDIO")
            self.conn.filter("Unique-ID", self.uuid)

            self.logger.info("[ESL_AUDIO] Connected and subscribed to UUID=%s", self.uuid)

            while self.running:
                event = self.conn.recvEventTimed(100)

                if not event:
                    continue

                if event.getHeader("Event-Name") == "CHANNEL_AUDIO":
                    audio_data = event.getBody()
                    if audio_data:
                        self.gateway.handle_rtp_packet(self.call_id, audio_data)

        except Exception as exc:  # pragma: no cover - relies on FreeSWITCH runtime
            self.logger.error("[ESL_AUDIO] Exception: %s", exc)
            traceback.print_exc()

    def stop(self) -> None:
        """Stop ESL consumption and tear down resources."""

        self.running = False
        if self.conn:
            self.conn.disconnect()
        self.logger.info("[ESL_AUDIO] Stopped for call_id=%s", self.call_id)


class FreeswitchRTPMonitor:
    """Monitor FreeSWITCH outbound RTP and feed ASR once 002.wav ends."""

    def __init__(
        self,
        gateway: "RealtimeGateway",
        rtp_protocol_factory: Optional[Callable[[], asyncio.DatagramProtocol]] = None,
    ):
        self.gateway = gateway
        self.logger = gateway.logger
        self.freeswitch_rtp_port: Optional[int] = None
        self.monitor_sock: Optional[socket.socket] = None
        self.monitor_transport: Optional[asyncio.BaseTransport] = None
        self.asr_active = False
        self.capture_thread: Optional[threading.Thread] = None
        self.capture_running = False
        self.active_receivers: Dict[str, ESLAudioReceiver] = {}
        self._rtp_protocol_factory = rtp_protocol_factory

    # --- ESL monitoring helpers -------------------------------------------------
    def get_rtp_port_from_freeswitch(self) -> Optional[int]:
        """Return the current FreeSWITCH RTP port via info files or uuid_dump."""

        import re

        try:
            rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
            if rtp_info_files:
                candidate_port = None
                candidate_uuid = None
                candidate_mtime = 0.0
                for filepath in rtp_info_files:
                    try:
                        mtime = filepath.stat().st_mtime
                        with open(filepath, "r") as file_obj:
                            content = file_obj.read()
                        port = None
                        uuid = None
                        for line in content.splitlines():
                            if line.startswith("local="):
                                local_rtp = line.split("=", 1)[1].strip()
                                if ":" in local_rtp:
                                    port_str = local_rtp.split(":")[-1]
                                    try:
                                        port = int(port_str)
                                    except ValueError:
                                        self.logger.debug(
                                            "[FS_RTP_MONITOR] Failed to parse port in %s: %s",
                                            filepath,
                                            local_rtp,
                                        )
                                        port = None
                            elif line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()

                        if port and mtime >= candidate_mtime:
                            candidate_mtime = mtime
                            candidate_port = port
                            candidate_uuid = uuid
                            self.logger.info(
                                "[FS_RTP_MONITOR] Candidate RTP info: file=%s port=%s uuid=%s mtime=%s",
                                filepath,
                                port,
                                uuid,
                                mtime,
                            )
                    except Exception as exc:  # pragma: no cover - debug logging only
                        self.logger.debug(
                            "[FS_RTP_MONITOR] Error reading RTP info file %s: %s",
                            filepath,
                            exc,
                        )

                if candidate_port:
                    self.logger.info(
                        "[FS_RTP_MONITOR] Selected RTP port %s (from RTP info files, latest matched)",
                        candidate_port,
                    )
                    if candidate_uuid and hasattr(self.gateway, "call_uuid_map"):
                        if hasattr(self.gateway, "ai_core") and hasattr(
                            self.gateway.ai_core, "call_id"
                        ):
                            latest_call_id = self.gateway.ai_core.call_id
                            if latest_call_id:
                                try:
                                    pre_map = dict(self.gateway.call_uuid_map)
                                except Exception:
                                    pre_map = {}
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTER] Registering uuid=%s for call_id=%s current_map=%s",
                                    candidate_uuid,
                                    latest_call_id,
                                    pre_map,
                                )
                                self.gateway.call_uuid_map[latest_call_id] = candidate_uuid
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTERED] Updated map=%s",
                                    self.gateway.call_uuid_map,
                                )
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Mapped call_id=%s -> uuid=%s",
                                    latest_call_id,
                                    candidate_uuid,
                                )
                    return candidate_port
        except Exception as exc:  # pragma: no cover - diagnostics only
            self.logger.debug(
                "[FS_RTP_MONITOR] Error reading RTP info files (non-fatal): %s", exc
            )

        try:
            result = subprocess.run(
                ["fs_cli", "-x", "show", "channels"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "[FS_RTP_MONITOR] fs_cli failed: %s", result.stderr
                )
                return None

            lines = result.stdout.strip().split("\n")
            if len(lines) < 2 or lines[0].startswith("0 total"):
                return None

            uuid = None
            for line in lines[1:]:
                if line.strip() and not line.startswith("uuid,"):
                    parts = line.split(",")
                    if parts and parts[0].strip():
                        uuid = parts[0].strip()
                        break

            if not uuid:
                return None

            dump_result = subprocess.run(
                ["fs_cli", "-x", f"uuid_dump {uuid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if dump_result.returncode != 0:
                self.logger.warning(
                    "[FS_RTP_MONITOR] uuid_dump failed for %s (non-fatal): %s",
                    uuid,
                    dump_result.stderr,
                )
                return None

            for line in dump_result.stdout.splitlines():
                if "variable_rtp_local_port" in line:
                    try:
                        port = int(line.split("=")[-1].strip())
                        self.logger.info(
                            "[FS_RTP_MONITOR] Found FreeSWITCH RTP port: %s (from uuid_dump of %s)",
                            port,
                            uuid,
                        )
                        return port
                    except (ValueError, IndexError):
                        self.logger.warning(
                            "[FS_RTP_MONITOR] Failed to parse variable_rtp_local_port from line: %s",
                            line,
                        )

            import re

            port_matches = re.findall(
                r"(?:local_media_port|rtp_local_media_port)[:=]\s*(\d+)",
                dump_result.stdout,
            )
            if port_matches:
                port = int(port_matches[0])
                self.logger.info(
                    "[FS_RTP_MONITOR] Found FreeSWITCH RTP port: %s (from uuid_dump of %s, fallback format)",
                    port,
                    uuid,
                )
                return port

            self.logger.warning(
                "[FS_RTP_MONITOR] RTP port not found in uuid_dump output for %s",
                uuid,
            )
            self.logger.debug(
                "[FS_RTP_MONITOR] uuid_dump output: %s", dump_result.stdout[:500]
            )
            return None
        except Exception as exc:  # pragma: no cover - runtime diagnostics
            self.logger.warning(
                "[FS_RTP_MONITOR] Error getting RTP port (non-fatal): %s", exc
            )
            return None

    def update_uuid_mapping_for_call(self, call_id: str) -> Optional[str]:
        """Resolve FreeSWITCH UUID for a call_id and update the shared map."""

        import re

        uuid = None

        try:
            port_candidates = []
            try:
                if (
                    hasattr(self, "fs_rtp_monitor")
                    and getattr(self.fs_rtp_monitor, "freeswitch_rtp_port", None)
                ):
                    port_candidates.append(self.fs_rtp_monitor.freeswitch_rtp_port)
            except Exception:
                pass
            try:
                if hasattr(self, "rtp_port") and self.rtp_port:
                    port_candidates.append(self.rtp_port)
            except Exception:
                pass

            for port in port_candidates:
                try:
                    found_uuid = self._find_rtp_info_by_port(port)
                    if found_uuid:
                        uuid = found_uuid
                        self.logger.info(
                            "[UUID_UPDATE] Found UUID from RTP info file by port: uuid=%s call_id=%s port=%s",
                            uuid,
                            call_id,
                            port,
                        )
                        break
                except Exception as exc:  # pragma: no cover - diagnostics only
                    self.logger.debug(
                        "[UUID_UPDATE] Error during port-based RTP info search for port=%s: %s",
                        port,
                        exc,
                    )

            if not uuid:
                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    latest_file = max(rtp_info_files, key=lambda p: p.stat().st_mtime)
                    with open(latest_file, "r") as file_obj:
                        lines = file_obj.readlines()
                        for line in lines:
                            if line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from RTP info file: uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break
        except Exception as exc:  # pragma: no cover - diagnostics only
            self.logger.debug("[UUID_UPDATE] Error reading RTP info file: %s", exc)

        if not uuid:
            try:
                result = subprocess.run(
                    ["fs_cli", "-x", "show", "channels"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) >= 2 and not lines[0].startswith("0 total"):
                        header_line = lines[0] if lines[0].startswith("uuid,") else None
                        headers = header_line.split(",") if header_line else []
                        uuid_pattern = re.compile(
                            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                            re.IGNORECASE,
                        )
                        for line in lines[1:]:
                            if not line.strip() or line.startswith("uuid,"):
                                continue
                            parts = line.split(",")
                            if not parts or not parts[0].strip():
                                continue
                            candidate_uuid = parts[0].strip()
                            if not uuid_pattern.match(candidate_uuid):
                                continue
                            if call_id in line:
                                uuid = candidate_uuid
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from show channels (matched call_id): uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break

                        if not uuid:
                            for line in lines[1:]:
                                if not line.strip() or line.startswith("uuid,"):
                                    continue
                                parts = line.split(",")
                                if parts and parts[0].strip():
                                    candidate_uuid = parts[0].strip()
                                    if uuid_pattern.match(candidate_uuid):
                                        uuid = candidate_uuid
                                        self.logger.warning(
                                            "[UUID_UPDATE] Using first available UUID (call_id match failed): uuid=%s call_id=%s",
                                            uuid,
                                            call_id,
                                        )
                                        break
            except Exception as exc:  # pragma: no cover - diagnostic path
                self.logger.warning(
                    "[UUID_UPDATE] Error getting UUID from show channels: %s", exc
                )

        if uuid and hasattr(self.gateway, "call_uuid_map"):
            old_uuid = self.gateway.call_uuid_map.get(call_id)
            self.gateway.call_uuid_map[call_id] = uuid
            if old_uuid != uuid:
                self.logger.info(
                    "[UUID_UPDATE] Updated mapping: call_id=%s old_uuid=%s -> new_uuid=%s",
                    call_id,
                    old_uuid,
                    uuid,
                )
            else:
                self.logger.debug(
                    "[UUID_UPDATE] Mapping unchanged: call_id=%s uuid=%s", call_id, uuid
                )
            return uuid

        return None

    async def start_monitoring(self) -> None:
        uuid = getattr(self.gateway, "uuid", None)
        if not uuid:
            self.logger.error("[ESL_MONITOR] UUID not found in gateway")
            return

        call_id = f"in-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-4]}"
        self.logger.info(
            "[ESL_MONITOR] Starting ESL audio monitoring for call_id=%s, uuid=%s",
            call_id,
            uuid,
        )

        esl_receiver = ESLAudioReceiver(call_id, uuid, self.gateway, self.logger)
        esl_receiver.start()
        self.active_receivers[call_id] = esl_receiver

        if hasattr(self.gateway, "call_uuid_map"):
            self.gateway.call_uuid_map[call_id] = uuid

        self.logger.info("[ESL_MONITOR] ESL monitoring started for call_id=%s", call_id)

    async def _check_asr_enable_flag(self) -> None:
        check_count = 0
        while self.gateway.running:
            try:
                check_count += 1
                flag_files = list(Path("/tmp").glob("asr_enable_*.flag"))
                if check_count % 20 == 0 or flag_files:
                    self.logger.debug(
                        "[FS_RTP_MONITOR] Checking ASR enable flag (check #%s, found %s flag file(s), asr_active=%s)",
                        check_count,
                        len(flag_files),
                        self.asr_active,
                    )

                if flag_files:
                    flag_file = flag_files[0]
                    if not self.asr_active:
                        self.logger.info(
                            "[SAFE_DELAY] 初回アナウンス完了検知、ASR起動を3秒遅延させます"
                        )
                        self._schedule_asr_enable_after_initial_sequence()
                    try:
                        flag_file.unlink()
                        self.logger.info(
                            "[FS_RTP_MONITOR] Removed ASR enable flag: %s", flag_file
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "[FS_RTP_MONITOR] Failed to remove flag file: %s", exc
                        )
            except Exception as exc:
                self.logger.error(
                    "[FS_RTP_MONITOR] Error checking ASR enable flag: %s",
                    exc,
                    exc_info=True,
                )

            await asyncio.sleep(0.5)

    async def _monitor_rtp_info_files(self) -> None:
        while self.gateway.running:
            try:
                if self.freeswitch_rtp_port and self.monitor_sock:
                    await asyncio.sleep(5.0)
                    continue

                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    candidate_port = None
                    candidate_mtime = 0.0
                    for filepath in rtp_info_files:
                        try:
                            mtime = filepath.stat().st_mtime
                            with open(filepath, "r") as file_obj:
                                for line in file_obj:
                                    if line.startswith("local="):
                                        local_rtp = line.split("=", 1)[1].strip()
                                        if ":" in local_rtp:
                                            try:
                                                port_str = local_rtp.split(":")[-1]
                                                port = int(port_str)
                                            except ValueError:
                                                continue
                                            if mtime >= candidate_mtime:
                                                candidate_mtime = mtime
                                                candidate_port = port
                        except Exception as exc:
                            self.logger.debug(
                                "[FS_RTP_MONITOR] Error reading RTP info file %s: %s",
                                filepath,
                                exc,
                            )

                    port = candidate_port
                    if not port:
                        await asyncio.sleep(2.0)
                        continue

                    if port and port != self.freeswitch_rtp_port:
                        self.logger.info(
                            "[FS_RTP_MONITOR] Found RTP port %s from RTP info files, starting monitoring...",
                            port,
                        )
                        self.freeswitch_rtp_port = port
                        try:
                            if SCAPY_AVAILABLE:
                                self.capture_running = True
                                self.capture_thread = threading.Thread(
                                    target=self._pcap_capture_loop,
                                    args=(self.freeswitch_rtp_port,),
                                    daemon=True,
                                )
                                self.capture_thread.start()
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Started pcap monitoring for FreeSWITCH RTP port %s (from RTP info file)",
                                    self.freeswitch_rtp_port,
                                )
                            else:
                                loop = asyncio.get_running_loop()
                                self.monitor_sock = socket.socket(
                                    socket.AF_INET, socket.SOCK_DGRAM
                                )
                                self.monitor_sock.setsockopt(
                                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
                                )
                                self.monitor_sock.setsockopt(
                                    socket.SOL_SOCKET, socket.SO_REUSEPORT, 1
                                )
                                self.monitor_sock.bind(("0.0.0.0", self.freeswitch_rtp_port))
                                self.monitor_sock.setblocking(False)

                                if not self._rtp_protocol_factory:
                                    raise RuntimeError(
                                        "RTP protocol factory not provided for monitor socket"
                                    )

                                self.monitor_transport, _ = await loop.create_datagram_endpoint(
                                    self._rtp_protocol_factory,
                                    sock=self.monitor_sock,
                                )
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Started UDP socket monitoring for FreeSWITCH RTP port %s (from RTP info file)",
                                    self.freeswitch_rtp_port,
                                )
                        except Exception as exc:
                            self.logger.error(
                                "[FS_RTP_MONITOR] Failed to start monitoring port %s: %s",
                                port,
                                exc,
                                exc_info=True,
                            )
                            self.freeswitch_rtp_port = None

                await asyncio.sleep(2.0)
            except Exception as exc:
                self.logger.error(
                    "[FS_RTP_MONITOR] Error in _monitor_rtp_info_files: %s",
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(2.0)

    def enable_asr(self) -> None:
        if not self.asr_active:
            self.asr_active = True
            self.logger.info(
                "[FS_RTP_MONITOR] ASR enabled after 002.wav playback completion"
            )

            if self.gateway and hasattr(self.gateway, "ai_core") and self.gateway.ai_core:
                call_id = getattr(self.gateway, "call_id", None)
                try:
                    current_map = getattr(self.gateway, "call_uuid_map", {})
                except Exception:
                    current_map = {}
                self.logger.warning(
                    "[DEBUG_ENABLE_ASR_ENTRY] call_id=%s call_uuid_map=%s",
                    call_id,
                    current_map,
                )

                if not call_id and hasattr(self.gateway, "_get_effective_call_id"):
                    call_id = self.gateway._get_effective_call_id()
                    self.logger.warning(
                        "[DEBUG_ENABLE_ASR_EFFECTIVE] effective_call_id=%s", call_id
                    )

                if not call_id:
                    self.logger.error(
                        "[ENABLE_ASR_FAILED] Cannot enable ASR: call_id is None. This indicates RTP monitoring has not started yet."
                    )
                    return

                uuid = None
                if call_id and hasattr(self.gateway, "call_uuid_map"):
                    uuid = self.gateway.call_uuid_map.get(call_id)

                if call_id and not uuid:
                    self.logger.warning(
                        "[ENABLE_ASR_UUID_MISSING] call_id=%s not in map, attempting update_uuid_mapping",
                        call_id,
                    )
                    uuid = self.update_uuid_mapping_for_call(call_id)

                client_id = getattr(self.gateway, "client_id", "000") or "000"
                self.logger.warning(
                    "[DEBUG_ENABLE_ASR_UUID] call_id=%s uuid=%s", call_id, uuid
                )

                if not uuid:
                    self.logger.error(
                        "[ENABLE_ASR_FAILED] Cannot enable ASR: uuid not found for call_id=%s. RTP info file may not exist yet.",
                        call_id,
                    )
                    return

                try:
                    self.gateway.ai_core.enable_asr(uuid, client_id=client_id)
                    self.logger.info(
                        "[ENABLE_ASR_SUCCESS] ASR enabled: uuid=%s call_id=%s client_id=%s",
                        uuid,
                        call_id,
                        client_id,
                    )
                except Exception as exc:
                    self.logger.error(
                        "[FS_RTP_MONITOR] Failed to call AICore.enable_asr(): %s",
                        exc,
                        exc_info=True,
                    )
            else:
                self.logger.warning(
                    "[FS_RTP_MONITOR] Cannot call AICore.enable_asr(): gateway or ai_core not available"
                )

    def _schedule_asr_enable_after_initial_sequence(
        self, base_delay: float = 3.0, max_wait: float = 10.0
    ) -> None:
        if self.asr_active:
            return

        gateway_timer = getattr(self.gateway, "_asr_enable_timer", None)
        if gateway_timer:
            try:
                gateway_timer.cancel()
            except Exception:
                pass

        def _runner() -> None:
            waited = 0.0
            initial_done = getattr(self.gateway, "initial_sequence_completed", False)
            if not initial_done:
                self.logger.info(
                    "[SAFE_DELAY] 初回アナウンス完了待ちでASR起動を遅延 (max_wait=%ss, base_delay=%ss)",
                    max_wait,
                    base_delay,
                )
            while (
                not getattr(self.gateway, "initial_sequence_completed", False)
                and waited < max_wait
            ):
                time.sleep(0.5)
                waited += 0.5
            if base_delay > 0:
                time.sleep(base_delay)
                waited += base_delay
            try:
                self.enable_asr()
                self.logger.info(
                    "[SAFE_DELAY] ASR enabled (waited=%.1fs, initial_sequence_completed=%s)",
                    waited,
                    getattr(self.gateway, "initial_sequence_completed", False),
                )
            except Exception as exc:
                self.logger.error(
                    "[SAFE_DELAY] Failed to enable ASR: %s", exc, exc_info=True
                )

        timer = threading.Timer(0.0, _runner)
        timer.daemon = True
        timer.start()
        self.gateway._asr_enable_timer = timer

    def _pcap_capture_loop(self, port: int) -> None:
        print(f"DEBUG_TRACE: _pcap_capture_loop ENTERED port={port}", flush=True)
        try:
            self.logger.info("[FS_RTP_MONITOR] Starting pcap capture for port %s", port)
            filter_str = f"udp dst port {port}"
            try:
                self.logger.info("[PCAP_CONFIG] Starting capture with filter: '%s'", filter_str)
            except Exception:
                pass
            try:
                print(
                    f"DEBUG_PRINT: Starting pcap with filter='{filter_str}'",
                    flush=True,
                )
            except Exception:
                pass
            sniff(
                filter=filter_str,
                prn=self._process_captured_packet,
                stop_filter=lambda _: not self.capture_running,
                store=False,
            )
        except Exception as exc:  # pragma: no cover - requires scapy & network
            self.logger.error(
                "[FS_RTP_MONITOR] Error in pcap capture loop: %s",
                exc,
                exc_info=True,
            )
        finally:
            self.logger.info(
                "[FS_RTP_MONITOR] pcap capture loop ended for port %s", port
            )

    def _process_captured_packet(self, packet) -> None:
        if not hasattr(self, "_packet_debug_count"):
            self._packet_debug_count = 0
        self._packet_debug_count += 1
        if self._packet_debug_count % 50 == 1:
            print(
                f"DEBUG_TRACE: _process_captured_packet called count={self._packet_debug_count}",
                flush=True,
            )
        try:
            if IP in packet and UDP in packet:
                ip_layer = packet[IP]
                udp_layer = packet[UDP]
                src_ip = ip_layer.src
                src_port = udp_layer.sport
                rtp_data = bytes(udp_layer.payload)

                if len(rtp_data) > 0:
                    addr = (src_ip, src_port)
                    self.logger.debug(
                        "[RTP_RECV] Captured %s bytes from %s (pcap)",
                        len(rtp_data),
                        addr,
                    )
                    self.logger.info(
                        "[RTP_RECV_RAW] from=%s, len=%s (pcap)", addr, len(rtp_data)
                    )
                    if len(rtp_data) > 12:
                        audio_payload_size = len(rtp_data) - 12
                        self.logger.debug(
                            "[RTP_AUDIO] RTP packet: total=%s bytes, header=12 bytes, audio_payload=%s bytes (pcap)",
                            len(rtp_data),
                            audio_payload_size,
                        )
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.gateway.handle_rtp_packet(rtp_data, addr)
                        )
                        loop.close()
                    except Exception as exc:
                        self.logger.error(
                            "[FS_RTP_MONITOR] Error processing captured packet: %s",
                            exc,
                            exc_info=True,
                        )
        except Exception as exc:  # pragma: no cover - diagnostic path
            self.logger.error(
                "[FS_RTP_MONITOR] Error in _process_captured_packet: %s",
                exc,
                exc_info=True,
            )

    async def stop_monitoring(self) -> None:
        self.capture_running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=5.0)
        if self.monitor_transport:
            self.monitor_transport.close()
        if self.monitor_sock:
            self.monitor_sock.close()
        self.logger.info("[FS_RTP_MONITOR] Stopped monitoring FreeSWITCH RTP port")

    # ------------------------------------------------------------------
    def _find_rtp_info_by_port(self, rtp_port: int) -> Optional[str]:
        try:
            rtp_info_files = glob.glob("/tmp/rtp_info_*.txt")
            self.logger.debug(
                "[RTP_INFO_SEARCH] port=%s total_files=%s",
                rtp_port,
                len(rtp_info_files),
            )
            for filepath in rtp_info_files:
                try:
                    with open(filepath, "r") as file_obj:
                        content = file_obj.read()
                        if f":{rtp_port}" in content:
                            for line in content.split("\n"):
                                if line.startswith("uuid="):
                                    uuid = line.split("=", 1)[1].strip()
                                    self.logger.info(
                                        "[RTP_INFO_FOUND] port=%s file=%s uuid=%s",
                                        rtp_port,
                                        filepath,
                                        uuid,
                                    )
                                    return uuid
                except Exception as exc:
                    self.logger.debug(
                        "[RTP_INFO_READ_ERROR] file=%s error=%s",
                        filepath,
                        exc,
                    )
                    continue

            self.logger.warning(
                "[RTP_INFO_NOT_FOUND] No file found for port=%s searched_files=%s",
                rtp_port,
                len(rtp_info_files),
            )
            return None
        except Exception as exc:  # pragma: no cover - diagnostic path
            self.logger.exception(
                "[RTP_INFO_SEARCH_ERROR] port=%s error=%s",
                rtp_port,
                exc,
            )
            return None
