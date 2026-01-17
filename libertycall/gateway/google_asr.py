"""GoogleASR クラス定義を ai_core から切り出したモジュール"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

from .google_asr_config import (
    GOOGLE_SPEECH_AVAILABLE,
    SpeechClient,
    build_recognition_config,
    build_streaming_config,
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
)

PRE_STREAM_BUFFER_DURATION_SEC = 0.3
DEBUG_RECORDING_DURATION_SEC = 5.0


class GoogleASR:
    """Google Cloud Speech-to-Text v1p1beta1 を使用したストリーミングASR実装"""

    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        language_code: str = "ja-JP",
        sample_rate: int = 16000,
        phrase_hints: Optional[List[str]] = None,
        ai_core: Optional[Any] = None,
        error_callback: Optional[Callable[[str, Exception], None]] = None,
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

    def _stream_worker(self) -> None:
        self.logger.info("[STREAM_WORKER_ENTRY] _stream_worker started")
        try:
            self.logger.info("[STREAM_WORKER_PRECHECK] About to start request generator")

            def _current_call_id() -> str:
                return getattr(self, "_current_call_id", "unknown")

            request_generator = build_request_generator(
                self._q,
                self._stop_event,
                self.logger,
                _current_call_id,
            )

            self.logger.info("[STREAM_WORKER_PRECHECK] Request generator defined")
            config = build_recognition_config(
                self.language_code,
                self.sample_rate,
                self.phrase_hints,
            )
            streaming_config = build_streaming_config(config)

            responses = self.client.streaming_recognize(
                config=streaming_config,
                requests=request_generator,
            )
            handle_streaming_responses(
                responses,
                logger=self.logger,
                ai_core=self.ai_core,
                current_call_id=lambda: getattr(self, "_current_call_id", "TEMP_CALL"),
                stream_start_time=lambda: getattr(self, "_stream_start_time", None),
                restart_flag_getter=lambda: getattr(self, "_restart_stream_scheduled", False),
                restart_flag_reset=lambda: setattr(self, "_restart_stream_scheduled", False),
            )
        except Exception as exc:
            self.logger.exception("GoogleASR._stream_worker: unexpected error: %s", exc)
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
            self._stream_thread = None
            self.logger.debug("GoogleASR._stream_worker: stop")
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
