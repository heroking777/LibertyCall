"""GoogleASR クラス定義を ai_core から切り出したモジュール"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
import wave
from typing import Any, Callable, Iterable, List, Optional, Tuple

from .google_asr_config import (
    GOOGLE_SPEECH_AVAILABLE,
    SpeechClient,
    build_recognition_config,
    build_streaming_config,
    cloud_speech,
    ensure_google_credentials,
    resolve_project_id,
)
from .google_asr_stream_helper import (
    StreamRecoveryPolicy,
    build_request_generator,
    feed_audio_chunk,
    flush_pre_stream_buffer,
    handle_streaming_responses,
    schedule_stream_recovery,
    _config_sent_calls,
    _config_lock,
)

PRE_STREAM_BUFFER_DURATION_SEC = 0.3
DEBUG_RECORDING_DURATION_SEC = 5.0
GASR_SAMPLE_RATE = int(os.environ.get("GASR_SAMPLE_RATE", "8000"))
GASR_LANGUAGE = os.environ.get("GASR_LANGUAGE", "ja-JP")
GASR_OUTPUT_DIR = os.environ.get("GASR_OUTPUT_DIR", "/tmp")
CAPTURE_MAX_BYTES = GASR_SAMPLE_RATE * 2 * 60  # 3秒分
RUN_ID = uuid.uuid4().hex
FRAME_MS = int(os.environ.get("GASR_FRAME_MS", "10"))
FRAME_BYTES = max(2, int(GASR_SAMPLE_RATE * 2 * FRAME_MS / 1000))
STREAMING_RPC_TIMEOUT_SEC = float(os.environ.get("GASR_RPC_TIMEOUT_SEC", "45"))
RPC_RUN_ID = uuid.uuid4().hex


class AudioFlowStats:
    """Thread-safe accumulator for audio pipeline counters."""

    def __init__(self, call_id: Optional[str] = None, sample_rate: int = GASR_SAMPLE_RATE) -> None:
        self._lock = threading.Lock()
        self.call_id = call_id or "unknown"
        self.frames_built = 0
        self.frames_bytes = 0
        self.enq_frames = 0
        self.enq_bytes = 0
        self.deq_frames = 0
        self.deq_bytes = 0
        self.req_cfg_yielded = 0
        self.req_audio_yielded = 0
        self.req_audio_bytes = 0
        self.sample_rate = sample_rate or GASR_SAMPLE_RATE
        self._capture_lock = threading.Lock()
        self.capture_max_bytes = CAPTURE_MAX_BYTES
        self.capture_pcm_path = f"{GASR_OUTPUT_DIR}/google_tx_{self.call_id}.pcm"
        self.capture_wav_path = f"{GASR_OUTPUT_DIR}/google_tx_{self.call_id}.wav"
        self._capture_bytes = 0
        self._capture_finalized = False
        self._logger = logging.getLogger("GoogleASR")

    def add_frames(self, frame_bytes: int) -> None:
        with self._lock:
            self.frames_built += 1
            self.frames_bytes += frame_bytes

    def add_enq(self, frame_bytes: int) -> None:
        with self._lock:
            self.enq_frames += 1
            self.enq_bytes += frame_bytes

    def add_deq(self, frame_bytes: int) -> None:
        with self._lock:
            self.deq_frames += 1
            self.deq_bytes += frame_bytes

    def add_req_cfg(self) -> None:
        with self._lock:
            self.req_cfg_yielded += 1

    def add_req_audio(self, audio_bytes: int) -> None:
        with self._lock:
            self.req_audio_yielded += 1
            self.req_audio_bytes += audio_bytes

    def capture_chunk(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._capture_lock:
            if self._capture_bytes >= self.capture_max_bytes:
                return
            remaining = self.capture_max_bytes - self._capture_bytes
            to_write = chunk[:remaining]
            try:
                os.makedirs(os.path.dirname(self.capture_pcm_path), exist_ok=True)
                with open(self.capture_pcm_path, "ab") as pcm:
                    pcm.write(to_write)
                self._capture_bytes += len(to_write)
            except Exception as exc:  # pragma: no cover
                self._logger.warning("[RPC_CAPTURE] write_failed uuid=%s err=%s", self.call_id, exc)

    def finalize_capture(self) -> None:
        with self._capture_lock:
            if self._capture_finalized:
                return
            try:
                if not self.call_id or self.call_id == "unknown":
                    self._logger.error(
                        "[CAPTURE] uuid_missing original=%s using=%s reason=%s",
                        getattr(self, "_original_call_id", None),
                        self.call_id,
                        "call_id_not_set",
                    )
                    print(
                        f"[CAPTURE] uuid_missing original={getattr(self, '_original_call_id', None)} using={self.call_id} reason=call_id_not_set",
                        flush=True,
                    )
                self._logger.error(
                    "[CAPTURE] finalize_start uuid=%s bytes=%s pcm=%s wav=%s",
                    self.call_id,
                    self._capture_bytes,
                    self.capture_pcm_path,
                    self.capture_wav_path,
                )
                print(
                    f"[CAPTURE] finalize_start uuid={self.call_id} bytes={self._capture_bytes} pcm={self.capture_pcm_path} wav={self.capture_wav_path}",
                    flush=True,
                )
                data = b""
                if os.path.exists(self.capture_pcm_path):
                    with open(self.capture_pcm_path, "rb") as pcm_file:
                        data = pcm_file.read()
                        self._logger.error(
                            "[CAPTURE] pcm_read uuid=%s bytes=%s path=%s",
                            self.call_id,
                            len(data),
                            self.capture_pcm_path,
                        )
                        print(
                            f"[CAPTURE] pcm_read uuid={self.call_id} bytes={len(data)} path={self.capture_pcm_path}",
                            flush=True,
                        )
                else:
                    # ensure directory exists so that downstream tools can inspect the pcm path
                    os.makedirs(os.path.dirname(self.capture_pcm_path), exist_ok=True)
                    with open(self.capture_pcm_path, "wb") as pcm_file:
                        pcm_file.write(b"")
                    self._logger.error(
                        "[CAPTURE] pcm_missing uuid=%s created_empty path=%s",
                        self.call_id,
                        self.capture_pcm_path,
                    )
                    print(
                        f"[CAPTURE] pcm_missing uuid={self.call_id} created_empty path={self.capture_pcm_path}",
                        flush=True,
                    )
                with wave.open(self.capture_wav_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(data)
                self._logger.error(
                    "[CAPTURE] wav_written uuid=%s bytes=%s path=%s",
                    self.call_id,
                    len(data),
                    self.capture_wav_path,
                )
                print(
                    f"[CAPTURE] wav_written uuid={self.call_id} bytes={len(data)} path={self.capture_wav_path}",
                    flush=True,
                )
                self._capture_finalized = True
                self._logger.error(
                    "[RPC_CAPTURE] saved uuid=%s pcm=%s wav=%s bytes=%d",
                    self.call_id,
                    self.capture_pcm_path,
                    self.capture_wav_path,
                    self._capture_bytes,
                )
            except Exception as exc:  # pragma: no cover
                self._logger.warning("[CAPTURE_ERR] finalize_failed uuid=%s err=%s", self.call_id, exc)
                try:
                    print(
                        f"[CAPTURE_ERR] finalize_failed uuid={self.call_id} type={type(exc).__name__} msg={exc}",
                        flush=True,
                    )
                except Exception:
                    pass
            finally:
                return {
                    "frames_built": self.frames_built,
                    "frames_bytes": self.frames_bytes,
                    "enq_frames": self.enq_frames,
                    "enq_bytes": self.enq_bytes,
                    "deq_frames": self.deq_frames,
                    "deq_bytes": self.deq_bytes,
                    "req_cfg_yielded": self.req_cfg_yielded,
                    "req_audio_yielded": self.req_audio_yielded,
                    "req_audio_bytes": self.req_audio_bytes,
                    "capture_pcm_path": self.capture_pcm_path if self._capture_bytes else None,
                    "capture_wav_path": self.capture_wav_path if self._capture_finalized else None,
                }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "frames_built": self.frames_built,
                "frames_bytes": self.frames_bytes,
                "enq_frames": self.enq_frames,
                "enq_bytes": self.enq_bytes,
                "deq_frames": self.deq_frames,
                "deq_bytes": self.deq_bytes,
                "req_cfg_yielded": self.req_cfg_yielded,
                "req_audio_yielded": self.req_audio_yielded,
                "req_audio_bytes": self.req_audio_bytes,
                "capture_pcm_path": self.capture_pcm_path if self._capture_bytes else None,
                "capture_wav_path": self.capture_wav_path if self._capture_finalized else None,
            }


class GoogleASR:
    """Google Cloud Speech-to-Text v1p1beta1 を使用したストリーミングASR実装"""

    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        language_code: str = GASR_LANGUAGE,
        sample_rate: int = GASR_SAMPLE_RATE,
        phrase_hints: Optional[List[str]] = None,
        ai_core: Optional[Any] = None,
        error_callback: Optional[Callable[[str, Exception], None]] = None,
        flow_stats: Optional[AudioFlowStats] = None,
    ) -> None:
        self.logger = logging.getLogger("GoogleASR")
        if not GOOGLE_SPEECH_AVAILABLE or SpeechClient is None:  # type: ignore[truthy-function]
            raise RuntimeError(
                "google-cloud-speech パッケージがインストールされていません。"
            )

        self.project_id = resolve_project_id(project_id, self.logger)
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.phrase_hints = phrase_hints or []
        self.ai_core = ai_core
        self._error_callback = error_callback

        self.credentials_path = ensure_google_credentials(credentials_path, self.logger)

        try:
            self.client = SpeechClient()  # type: ignore[call-arg]
        except Exception as exc:  # pragma: no cover - init error logging
            self.logger.error("GoogleASR: 初期化失敗: %s", exc)
            raise

        self._q: queue.Queue[bytes] = queue.Queue(maxsize=500)
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pre_stream_buffer: bytearray = bytearray()
        self._pre_stream_buffer_max_bytes = int(16000 * 2 * PRE_STREAM_BUFFER_DURATION_SEC)
        self._debug_raw = bytearray()
        self._debug_max_bytes = int(16000 * 2 * DEBUG_RECORDING_DURATION_SEC)
        self._restart_stream_scheduled = False
        self._flow_stats = flow_stats or AudioFlowStats()
        self._stream_start_time = None
        self._recovery_policy = StreamRecoveryPolicy()

    # --- 以下、元の ai_core.py から移植したメソッド ---
    # 実装は ai_core.py と同一で、参照箇所のみ変更なし
    def _start_stream_worker(self, call_id: str) -> None:
        self._stream_start_time = time.time()
        self.logger.info(
            "[ASR_STREAM] Recording stream start time: %.2f for call_id=%s",
            self._stream_start_time,
            call_id,
        )
        # Ensure capture paths include the active call id.
        try:
            self._flow_stats = AudioFlowStats(call_id=call_id, sample_rate=self.sample_rate)
        except Exception as exc:  # pragma: no cover
            self.logger.warning("[CAPTURE_ERR] flow_stats_reset_failed call_id=%s err=%s", call_id, exc)
        self._restart_stream_scheduled = False
        if hasattr(self.ai_core, "call_uuid_map"):
            found = None
            for mapped_call_id, mapped_uuid in self.ai_core.call_uuid_map.items():
                if mapped_uuid == call_id:
                    found = mapped_call_id
                    break
            self._current_call_id = found if found else call_id
        else:
            self._current_call_id = call_id

        if self._stream_thread is not None and self._stream_thread.is_alive():
            self.logger.warning(
                "[GHOST_THREAD_DETECTED] ASR stream thread already running for call_id=%s",
                call_id,
            )
            if len(self._pre_stream_buffer) > 0:
                self._flush_pre_stream_buffer()
            return

        self._stop_event.clear()
        self._stream_thread = threading.Thread(
            target=self._stream_worker,
            daemon=False,
            name=f"GoogleASR-{call_id}",
        )
        self._stream_thread.start()
        time.sleep(0.01)
        self.logger.info(
            "GoogleASR: STREAM_WORKER_START call_id=%s thread_alive=%s",
            call_id,
            self._stream_thread.is_alive(),
        )
        self.logger.error(
            "[GASR_THREAD] started call_id=%s thread=%s",
            call_id,
            self._stream_thread.name,
        )

    def _stream_worker(self) -> None:
        self.logger.info("[STREAM_WORKER_ENTRY] _stream_worker started")
        rpc_started = False
        rpc_resp_count = 0
        rpc_end_reason = "not_started"
        rpc_logger = None
        last_step = 0
        call_uuid = getattr(self, "_current_call_id", None) or "unknown"
        try:
            last_step = 10
            self.logger.error("[SW] step=10 enter thread=%s self=%s uuid=%s", threading.get_ident(), hex(id(self)), call_uuid)
            self.logger.info("[STREAM_WORKER_PRECHECK] About to start request generator")

            def _current_call_id() -> str:
                return getattr(self, "_current_call_id", "unknown")

            last_step = 20
            call_uuid = _current_call_id()
            self.logger.error("[SW] step=20 got_call_uuid uuid=%s", call_uuid)

            config = build_recognition_config(
                self.language_code,
                self.sample_rate,
                self.phrase_hints,
            )

            simple_cfg = os.getenv("LIBERTYCALL_ASR_SIMPLE_CFG", "0") == "1"
            if simple_cfg:
                # テスト用にもっとも素直な設定へ落とす
                if hasattr(config, "use_enhanced"):
                    config.use_enhanced = True
                if hasattr(config, "model"):
                    try:
                        delattr(config, "model")
                    except AttributeError:
                        config.model = "telephony"

            streaming_config = build_streaming_config(config)
            if simple_cfg:
                streaming_config.interim_results = True
                streaming_config.single_utterance = False
                streaming_config.enable_voice_activity_events = False
            last_step = 30
            self.logger.error("[SW] step=30 flow_stats_ready uuid=%s has_stats=%s", call_uuid, bool(self._flow_stats))
            request_generator = build_request_generator(
                self._q,
                self._stop_event,
                self.logger,
                _current_call_id,
                flow_stats=self._flow_stats,
            )
            self.logger.error(
                "[REQGEN] created uuid=%s obj=%s",
                call_uuid,
                hex(id(request_generator)),
            )
            last_step = 60
            self.logger.error("[SW] step=60 ensure_config_first_ok uuid=%s", call_uuid)

            rpc_session_id = f"{RPC_RUN_ID}-{uuid.uuid4().hex[:8]}"
            cfg_summary = _summarize_streaming_config(streaming_config)
            self.logger.error(
                "[RPC] start run=%s uuid=%s %s simple_cfg=%s interim=%s single_utt=%s voice_events=%s deadline=%.1fs",
                rpc_session_id,
                call_uuid,
                cfg_summary,
                simple_cfg,
                getattr(streaming_config, "interim_results", None),
                getattr(streaming_config, "single_utterance", None),
                getattr(streaming_config, "enable_voice_activity_events", None),
                STREAMING_RPC_TIMEOUT_SEC,
            )
            self.logger.info("[STREAM_WORKER_PRECHECK] Request generator defined")
            self.logger.error(
                "[GASR_CALL] start streaming_recognize call_id=%s lang=%s rate=%s encoding=%s interim=%s",
                getattr(self, "_current_call_id", "unknown"),
                self.language_code,
                self.sample_rate,
                "LINEAR16",
                getattr(streaming_config, "interim_results", None),
            )

            self.logger.error(
                "[REQGEN] passed_to_grpc uuid=%s obj=%s",
                call_uuid,
                hex(id(request_generator)),
            )

            # CONFIG is sent via the config= argument only (requests are AUDIO-only)
            self.logger.error("[REQTRACE] seq=0 type=CONFIG bytes=0 note=config_arg")

            responses = self.client.streaming_recognize(
                config=streaming_config,
                requests=request_generator,
                timeout=STREAMING_RPC_TIMEOUT_SEC,
            )
            last_step = 70
            self.logger.error("[SW] step=70 rpc_call_start uuid=%s timeout=%.1f", call_uuid, STREAMING_RPC_TIMEOUT_SEC)
            rpc_started = True
            self.logger.error("[RPC] iterator_created run=%s uuid=%s", rpc_session_id, call_uuid)
            rpc_logger = _RPCLoggedResponses(responses, self.logger, rpc_session_id, call_uuid)
            last_step = 80
            self.logger.error("[SW] step=80 rpc_iterator_created uuid=%s", call_uuid)
            last_step = 81
            self.logger.error("[SW] step=81 after_iterator_created uuid=%s", call_uuid)
            self.logger.error(
                "[GASR_CALL] streaming_recognize returned iterator call_id=%s",
                getattr(self, "_current_call_id", "unknown"),
            )
            last_step = 82
            self.logger.error("[SW] step=82 before_resp_loop uuid=%s", call_uuid)
            last_step = 83
            self.logger.error("[SW] step=83 resp_loop_enter uuid=%s", call_uuid)
            handle_streaming_responses(
                rpc_logger,
                logger=self.logger,
                ai_core=self.ai_core,
                current_call_id=lambda: getattr(self, "_current_call_id", "TEMP_CALL"),
                stream_start_time=lambda: getattr(self, "_stream_start_time", None),
                restart_flag_getter=lambda: getattr(self, "_restart_stream_scheduled", False),
                restart_flag_reset=lambda: setattr(self, "_restart_stream_scheduled", False),
            )
            last_step = 95
            self.logger.error("[SW] step=95 resp_loop_end uuid=%s resp_count=%s", call_uuid, rpc_logger.count)
            rpc_resp_count = rpc_logger.count
            rpc_end_reason = rpc_logger.end_reason or "StopIteration"
        except Exception as exc:
            self.logger.exception("GoogleASR._stream_worker: unexpected error: %s", exc)
            self.logger.error(
                "[GASR_CALL_ERR] streaming_recognize failed call_id=%s err=%s",
                getattr(self, "_current_call_id", "unknown"),
                exc,
            )
            self.logger.error(
                "[SW_EXC] step=%s uuid=%s type=%s msg=%s",
                last_step,
                call_uuid,
                type(exc).__name__,
                exc,
            )
            if rpc_logger and not rpc_logger.end_reason:
                rpc_end_reason = f"exception:{type(exc).__name__}"
            call_id = getattr(self, "_current_call_id", None) or "TEMP_CALL"
            if self._error_callback is not None:
                try:
                    self._error_callback(call_id, exc)
                except Exception as cb_err:  # pragma: no cover
                    self.logger.exception("GoogleASR._stream_worker: error_callback failed: %s", cb_err)

            error_msg = str(exc).lower()
            is_permanent_error = any(
                keyword in error_msg
                for keyword in [
                    "credentials",
                    "authentication",
                    "permission",
                    "unauthorized",
                    "forbidden",
                    "not found",
                    "invalid",
                ]
            )
            if not is_permanent_error:
                self.logger.info("[ASR_RECOVERY] Attempting to restart ASR stream worker...")
                schedule_stream_recovery(
                    self._recovery_policy,
                    self._start_stream_worker,
                    self._stop_event,
                    self.logger,
                    getattr(self, "_current_call_id", None),
                )
        finally:
            if last_step < 83:
                self.logger.error(
                    "[SW] step=85 early_exit reason=%s uuid=%s",
                    f"last_step={last_step}",
                    call_uuid,
                )
            self.logger.error("[SW] step=99 finally uuid=%s", getattr(self, "_current_call_id", None))
            self._stream_thread = None
            self.logger.debug("GoogleASR._stream_worker: stop")
            self.logger.error(
                "[GASR_THREAD] end call_id=%s",
                getattr(self, "_current_call_id", "unknown"),
            )
            try:
                if self._debug_raw:
                    debug_path = "/tmp/google_chunk.raw"
                    with open(debug_path, "wb") as file:
                        file.write(self._debug_raw)
                    self.logger.info(
                        "GoogleASR: DEBUG_RAW_DUMP: path=%s bytes=%d",
                        debug_path,
                        len(self._debug_raw),
                    )
            except Exception as dump_err:  # pragma: no cover
                self.logger.exception("GoogleASR: DEBUG_RAW_DUMP_FAILED: %s", dump_err)
            call_uuid = getattr(self, "_current_call_id", "unknown")
            self._log_flow_summary(
                call_uuid,
                self._flow_stats,
                rpc_started,
                rpc_resp_count,
                rpc_end_reason,
            )

    def _flush_pre_stream_buffer(self) -> None:
        flush_pre_stream_buffer(self._pre_stream_buffer, self._q, self.logger)

    def feed_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        feed_audio_chunk(
            call_id,
            pcm16k_bytes,
            stop_event=self._stop_event,
            stream_thread_getter=lambda: self._stream_thread,
            pre_stream_buffer=self._pre_stream_buffer,
            pre_stream_buffer_max_bytes=self._pre_stream_buffer_max_bytes,
            debug_raw=self._debug_raw,
            debug_max_bytes=self._debug_max_bytes,
            audio_queue=self._q,
            start_stream_worker=self._start_stream_worker,
            logger=self.logger,
            flush_buffer=self._flush_pre_stream_buffer,
            flow_stats=self._flow_stats,
        )

    def poll_result(self, call_id: str) -> Optional[Tuple[str, float, float, float]]:
        return None

    def end_stream(self, call_id: str) -> None:
        self.logger.info("GoogleASR.end_stream: call_id=%s", call_id)
        self._stop_event.set()
        if self._stream_thread and self._stream_thread.is_alive():
            try:
                self._q.put_nowait(None)  # type: ignore[arg-type]
            except queue.Full:
                self.logger.warning("GoogleASR.end_stream: queue full while ending stream")
            self._stream_thread.join(timeout=2.0)
        self._stream_thread = None
        self._pre_stream_buffer.clear()
        self._debug_raw.clear()

        # Always finalize capture so that google_tx_<uuid>.wav exists even on early exits.
        try:
            if self._flow_stats:
                self._flow_stats.finalize_capture()
        except Exception as exc:  # pragma: no cover
            self.logger.warning("[CAPTURE_ERR] finalize_capture_failed call_id=%s err=%s", call_id, exc)

    def feed(self, call_id: str, pcm16k_bytes: bytes) -> None:
        self.feed_audio(call_id, pcm16k_bytes)

    def reset_call(self, call_id: str) -> None:
        self.logger.info("GoogleASR.reset_call: call_id=%s", call_id)
        self.end_stream(call_id)
        self._q = queue.Queue(maxsize=500)
        self._pre_stream_buffer.clear()
        self._debug_raw.clear()
        self._stop_event.clear()
        self._restart_stream_scheduled = False
        self._stream_start_time = None
        
        # 【100%確実ガード】リセット時にConfig送信済みフラグをクリア
        global _config_sent_calls, _config_lock
        with _config_lock:
            if call_id in _config_sent_calls:
                _config_sent_calls.remove(call_id)
                self.logger.info("[CONFIG_FLAG_RESET] Cleared config sent flag for call_id=%s", call_id)

    def _log_flow_summary(
        self,
        call_uuid: str,
        flow_stats: Optional[AudioFlowStats] = None,
        rpc_started: bool = False,
        rpc_resp_count: int = 0,
        rpc_end_reason: str = "",
    ) -> None:
        try:
            stats = flow_stats or self._flow_stats
            snapshot = stats.snapshot() if stats else {}
        except Exception as exc:  # pragma: no cover
            snapshot = {}
            try:
                self.logger.warning(
                    "[FLOW] snapshot_failed uuid=%s err=%s",
                    call_uuid,
                    exc,
                )
            except Exception:
                pass

        try:
            self.logger.error(
                "[FLOW] uuid=%s enq_frames=%s enq_bytes=%s deq_frames=%s deq_bytes=%s req_cfg=%s req_audio=%s req_audio_bytes=%s rpc_started=%s rpc_resp_count=%s rpc_end_reason=%s",
                call_uuid,
                snapshot.get("enq_frames"),
                snapshot.get("enq_bytes"),
                snapshot.get("deq_frames"),
                snapshot.get("deq_bytes"),
                snapshot.get("req_cfg_yielded"),
                snapshot.get("req_audio_yielded"),
                snapshot.get("req_audio_bytes"),
                int(bool(rpc_started)),
                rpc_resp_count,
                rpc_end_reason,
            )
        except Exception as exc:  # pragma: no cover
            try:
                self.logger.error("[FLOW_ERR] uuid=%s type=%s msg=%s", call_uuid, type(exc).__name__, exc)
            except Exception:
                pass


def ensure_config_first(
    audio_iter: Iterable["cloud_speech.StreamingRecognizeRequest"],
    streaming_config: "cloud_speech.StreamingRecognitionConfig",
    logger: logging.Logger,
    call_id_getter: Optional[Callable[[], str]] = None,
    flow_stats: Optional[AudioFlowStats] = None,
) -> Iterable["cloud_speech.StreamingRecognizeRequest"]:
    call_id = call_id_getter() if call_id_getter else "unknown"
    seq = 0
    audio_count = 0
    audio_bytes = 0
    inner_config_dropped = 0
    after_drop_logged = False
    first_audio_logged = False

    def has_audio(req):
        try:
            data = getattr(req, "audio_content", None)
            return data is not None and len(data) > 0
        except Exception:
            return False

    def log_req(req, note: str) -> "cloud_speech.StreamingRecognizeRequest":
        nonlocal seq
        audio_len = len(req.audio_content) if has_audio(req) else 0
        req_type = "CONFIG" if getattr(req, "streaming_config", None) else ("AUDIO" if audio_len else "OTHER")
        logger.error(
            "[REQTRACE] seq=%d type=%s bytes=%d note=%s",
            seq,
            req_type,
            audio_len,
            note,
        )
        if flow_stats:
            if req_type == "CONFIG":
                flow_stats.add_req_cfg()
            elif req_type == "AUDIO" and audio_len:
                flow_stats.add_req_audio(audio_len)
        seq += 1
        return req

    def generator():
        nonlocal audio_count, audio_bytes, inner_config_dropped, after_drop_logged, first_audio_logged
        logger.warning("[REQGEN] yielded_config uuid=%s", call_id)
        yield log_req(
            cloud_speech.StreamingRecognizeRequest(streaming_config=streaming_config),
            "outer_config",
        )
        for req in audio_iter:
            # Inner iterator must be AUDIO only. If it yields CONFIG, drop it.
            if getattr(req, "streaming_config", None) is not None:
                inner_config_dropped += 1
                logger.error(
                    "[REQTRACE] seq=%d type=CONFIG bytes=0 note=drop_inner_config",
                    seq,
                )
                if flow_stats:
                    flow_stats.add_req_cfg()
                if not after_drop_logged:
                    logger.warning(
                        "[REQGEN] after_drop_inner_config uuid=%s inner_config_dropped=%d next_expected=AUDIO",
                        call_id,
                        inner_config_dropped,
                    )
                    after_drop_logged = True
                continue
            audio_len = len(req.audio_content) if has_audio(req) else 0
            if audio_len:
                audio_count += 1
                audio_bytes += audio_len
                if not first_audio_logged:
                    logger.warning(
                        "[REQGEN] first_audio_yielded uuid=%s bytes=%d",
                        call_id,
                        audio_len,
                    )
                    first_audio_logged = True
                if audio_count <= 10 or audio_count % 100 == 0:
                    logger.warning(
                        "[REQGEN] yielded_audio uuid=%s count=%d bytes_total=%d",
                        call_id,
                        audio_count,
                        audio_bytes,
                    )
                yield log_req(req, "audio")
            else:
                yield log_req(req, "non_audio")
        logger.warning(
            "[REQGEN] audio_iter_complete uuid=%s audio_count=%d bytes_total=%d inner_config_dropped=%d",
            call_id,
            audio_count,
            audio_bytes,
            inner_config_dropped,
        )

    return generator()


def _summarize_streaming_config(streaming_config: "cloud_speech.StreamingRecognitionConfig") -> str:
    cfg = getattr(streaming_config, "config", None)
    encoding = None
    sample_rate = None
    language = None
    enhanced = None
    model = None
    if cfg is not None:
        encoding_value = getattr(cfg, "encoding", None)
        try:
            encoding = cloud_speech.RecognitionConfig.AudioEncoding.Name(encoding_value)
        except Exception:  # pragma: no cover
            encoding = str(encoding_value)
        sample_rate = getattr(cfg, "sample_rate_hertz", None)
        language = getattr(cfg, "language_code", None)
        enhanced = getattr(cfg, "use_enhanced", None)
        model = getattr(cfg, "model", None)
    interim = getattr(streaming_config, "interim_results", None)
    single_utt = getattr(streaming_config, "single_utterance", None)
    vae = getattr(streaming_config, "enable_voice_activity_events", None)
    return (
        f"encoding={encoding} sample_rate={sample_rate} language={language} "
        f"interim={interim} single_utt={single_utt} voice_events={vae} enhanced={enhanced} model={model}"
    )


class _RPCLoggedResponses:
    def __init__(self, responses, logger: logging.Logger, run_id: str, call_id: str):
        self._responses = responses
        self.logger = logger
        self.run_id = run_id
        self.call_id = call_id
        self.count = 0
        self.end_reason: Optional[str] = None

    def __iter__(self):
        return self._gen()

    def _gen(self):
        self.logger.error("[RPC] resp_loop_start run=%s uuid=%s", self.run_id, self.call_id)
        try:
            for response in self._responses:
                self.count += 1
                has_results = bool(response.results)
                first_result = response.results[0] if response.results else None
                is_final = bool(getattr(first_result, "is_final", False)) if first_result else False
                transcript_len = 0
                transcript = ""
                confidence = 0.0
                alternatives_count = 0
                
                # 詳細なデバッグ情報
                if first_result:
                    alternatives_count = len(getattr(first_result, "alternatives", []))
                    if getattr(first_result, "alternatives", None) and len(first_result.alternatives) > 0:
                        alt = first_result.alternatives[0]
                        transcript = getattr(alt, "transcript", "") or ""
                        transcript_len = len(transcript)
                        confidence = getattr(alt, "confidence", 0.0)
                
                speech_event_value = getattr(response, "speech_event_type", None)
                speech_event = _speech_event_name(speech_event_value)
                
                # 詳細ログ
                self.logger.error(
                    "[RPC_DEBUG] n=%d has_results=%s is_final=%s alt_count=%d transcript='%s' confidence=%.3f speech_event=%s",
                    self.count,
                    has_results,
                    is_final,
                    alternatives_count,
                    transcript[:50] if transcript else "",
                    confidence,
                    speech_event,
                )
                yield response
            self.end_reason = "StopIteration"
            self.logger.error(
                "[RPC] resp_loop_end reason=%s run=%s uuid=%s resp_count=%d",
                self.end_reason,
                self.run_id,
                self.call_id,
                self.count,
            )
        except Exception as exc:
            status_code = None
            try:
                status_code = exc.code() if callable(getattr(exc, "code", None)) else getattr(exc, "code", None)
            except Exception:  # pragma: no cover
                status_code = getattr(exc, "code", None)
            details = None
            try:
                details = exc.details() if callable(getattr(exc, "details", None)) else getattr(exc, "details", None)
            except Exception:  # pragma: no cover
                details = getattr(exc, "details", None)
            self.end_reason = f"exception:{type(exc).__name__}"
            self.logger.error(
                "[RPC] exception run=%s uuid=%s type=%s code=%s details=%s",
                self.run_id,
                self.call_id,
                type(exc).__name__,
                status_code,
                details,
            )
            self.logger.error(
                "[RPC] resp_loop_end reason=%s run=%s uuid=%s resp_count=%d",
                type(exc).__name__,
                self.run_id,
                self.call_id,
                self.count,
            )
            raise


def _speech_event_name(value: Optional[int]) -> Optional[str]:
    if value is None or cloud_speech is None:
        return value
    try:
        return cloud_speech.StreamingRecognizeResponse.SpeechEventType.Name(value)
    except Exception:  # pragma: no cover
        return str(value)
