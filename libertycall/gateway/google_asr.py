"""GoogleASR クラス定義を ai_core から切り出したモジュール"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

try:
    from google.cloud.speech_v1p1beta1 import SpeechClient  # type: ignore
    from google.cloud.speech_v1p1beta1.types import cloud_speech  # type: ignore
    GOOGLE_SPEECH_AVAILABLE = True
except ImportError:
    SpeechClient = None  # type: ignore
    cloud_speech = None  # type: ignore
    GOOGLE_SPEECH_AVAILABLE = False

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
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            potential_path = "/opt/libertycall/config/google-credentials.json"
            if os.path.exists(potential_path):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = potential_path
                self.logger.info(
                    "Force set GOOGLE_APPLICATION_CREDENTIALS to %s", potential_path
                )

        if not GOOGLE_SPEECH_AVAILABLE or SpeechClient is None:  # type: ignore[truthy-function]
            raise RuntimeError(
                "google-cloud-speech パッケージがインストールされていません。"
            )

        self.project_id = project_id or os.getenv("LC_GOOGLE_PROJECT_ID") or "libertycall-main"
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.phrase_hints = phrase_hints or []
        self.ai_core = ai_core
        self._error_callback = error_callback

        if not self.project_id:
            self.logger.warning("LC_GOOGLE_PROJECT_ID が未設定です。デフォルトを使用します。")
            self.project_id = "libertycall-main"

        cand_paths: List[str] = []
        env_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if env_creds:
            cand_paths.append(env_creds)
        env_lc_creds = os.getenv("LC_GOOGLE_CREDENTIALS_PATH")
        if env_lc_creds and env_lc_creds not in cand_paths:
            cand_paths.append(env_lc_creds)
        if credentials_path:
            cand_paths.append(credentials_path)
        cand_paths.extend(
            [
                "/opt/libertycall/key/google_tts.json",
                "/opt/libertycall/key/libertycall-main-7e4af202cdff.json",
            ]
        )

        self.credentials_path = None
        for path in cand_paths:
            if path and os.path.exists(path):
                self.credentials_path = path
                break

        if self.credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
            self.logger.info("GoogleASR: using credentials file: %s", self.credentials_path)
        else:
            self.logger.error("GoogleASR: no valid credentials file found.")

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

            def request_generator_from_queue():
                self.logger.warning(
                    "[REQUEST_GEN_ENTRY] Generator START for call_id=%s",
                    getattr(self, "_current_call_id", "unknown"),
                )
                print(
                    f"[REQUEST_GEN_ENTRY] Generator START for call_id={getattr(self, '_current_call_id', 'unknown')}",
                    flush=True,
                )

                empty_count = 0
                while not self._stop_event.is_set():
                    try:
                        chunk = self._q.get(timeout=0.1)
                        if chunk is None:
                            self.logger.info("[REQUEST_GEN] Received sentinel (None), stopping generator")
                            return
                        self.logger.warning(
                            "[REQUEST_GEN_DATA] Got chunk from queue, size=%d", len(chunk)
                        )
                        print(
                            f"[REQUEST_GEN_DATA] Got chunk from queue, size={len(chunk)}",
                            flush=True,
                        )
                        empty_count = 0
                    except queue.Empty:
                        if self._stop_event.is_set():
                            break
                        empty_count += 1
                        if empty_count >= 10:
                            empty_count = 0
                            self.logger.debug("[ASR_GEN] Emitting keepalive empty audio chunk")
                            yield cloud_speech.StreamingRecognizeRequest(audio_content=b"")  # type: ignore[arg-type]
                        continue

                    if chunk is None:
                        break
                    if not isinstance(chunk, bytes) or len(chunk) == 0:
                        continue
                    self.logger.debug("[ASR_GEN] Yielding audio request")
                    yield cloud_speech.StreamingRecognizeRequest(audio_content=chunk)  # type: ignore[arg-type]

            self.logger.info("[STREAM_WORKER_PRECHECK] Request generator defined")
            config = cloud_speech.RecognitionConfig(  # type: ignore[call-arg]
                encoding=cloud_speech.RecognitionConfig.AudioEncoding.LINEAR16,  # type: ignore[attr-defined]
                sample_rate_hertz=16000,
                language_code=self.language_code,
                use_enhanced=True,
                audio_channel_count=1,
                enable_separate_recognition_per_channel=False,
                enable_automatic_punctuation=True,
                max_alternatives=1,
                speech_contexts=[],
            )
            if self.phrase_hints:
                config.speech_contexts = [
                    cloud_speech.SpeechContext(phrases=self.phrase_hints)  # type: ignore[attr-defined]
                ]

            streaming_config = cloud_speech.StreamingRecognitionConfig(  # type: ignore[call-arg]
                config=config,
                interim_results=True,
                single_utterance=False,
            )

            responses = self.client.streaming_recognize(
                config=streaming_config,
                requests=request_generator_from_queue(),
            )

            for response in responses:
                results_count = len(response.results) if response.results else 0
                error_code = response.error.code if response.error else None
                self.logger.warning(
                    "[ASR_RESPONSE_RECEIVED] results=%s, error_code=%s",
                    results_count,
                    error_code,
                )

                stream_start_time = getattr(self, "_stream_start_time", None)
                if stream_start_time and time.time() - stream_start_time >= 280.0:
                    call_id = getattr(self, "_current_call_id", "TEMP_CALL")
                    self.logger.warning(
                        "[ASR_AUTO_RESTART] Stream duration limit approaching for call_id=%s",
                        call_id,
                    )

                self.logger.info("GoogleASR: STREAM_RESPONSE: %s", response)
                for result in response.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    transcript = alt.transcript
                    is_final = result.is_final
                    confidence = alt.confidence if getattr(alt, "confidence", 0.0) else 0.0

                    self.logger.debug(
                        "[ASR_DEBUG] google_raw call_id=%s is_final=%s transcript=%r confidence=%s",
                        getattr(self, "_current_call_id", None) or "TEMP_CALL",
                        is_final,
                        transcript,
                        confidence if confidence else None,
                    )
                    self.logger.info(
                        "GoogleASR: ASR_GOOGLE_RAW: final=%s conf=%.3f text=%s",
                        is_final,
                        confidence,
                        transcript,
                    )
                    if self.ai_core:
                        try:
                            call_id = getattr(self, "_current_call_id", "TEMP_CALL")
                            if not is_final:
                                text_stripped = transcript.strip() if transcript else ""
                                if 1 <= len(text_stripped) <= 6:
                                    backchannel_keywords = ["はい", "えっと", "あの", "ええ", "そう", "うん", "ああ"]
                                    if any(keyword in text_stripped for keyword in backchannel_keywords):
                                        self.logger.debug(
                                            "[BACKCHANNEL_TRIGGER_ASR] Detected short utterance: %s",
                                            text_stripped,
                                        )
                                        if hasattr(self.ai_core, "tts_callback") and self.ai_core.tts_callback:  # type: ignore[attr-defined]
                                            try:
                                                import asyncio

                                                try:
                                                    loop = asyncio.get_event_loop()
                                                    loop.create_task(
                                                        asyncio.to_thread(
                                                            self.ai_core.tts_callback,  # type: ignore[misc]
                                                            call_id,
                                                            "はい",
                                                            None,
                                                            False,
                                                        )
                                                    )
                                                except RuntimeError:
                                                    self.ai_core.tts_callback(call_id, "はい", None, False)  # type: ignore[misc]
                                                self.logger.info(
                                                    "[BACKCHANNEL_SENT_ASR] call_id=%s text='はい'",
                                                    call_id,
                                                )
                                            except Exception as err:  # pragma: no cover
                                                self.logger.exception(
                                                    "[BACKCHANNEL_ERROR_ASR] call_id=%s error=%s",
                                                    call_id,
                                                    err,
                                                )
                            self.ai_core.on_transcript(call_id, transcript, is_final=is_final)
                        except Exception as err:  # pragma: no cover
                            self.logger.exception("GoogleASR: on_transcript 呼び出しエラー: %s", err)

                    if is_final:
                        self.logger.info(
                            "GoogleASR: ASR_GOOGLE_FINAL: conf=%.3f text=%s",
                            confidence,
                            transcript,
                        )
                        self.logger.info("[ASR_RESULT] \"%s\"", transcript)

            if getattr(self, "_restart_stream_scheduled", False):
                call_id = getattr(self, "_current_call_id", "TEMP_CALL")
                self.logger.info(
                    "[ASR_AUTO_RESTART] Scheduled restart suppressed for call_id=%s",
                    call_id,
                )
                self._restart_stream_scheduled = False
                return
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
                self.logger.info("[ASR_RECOVERY] Attempting to restart ASR stream worker in 3 seconds...")

                def _recover_stream_worker():
                    time.sleep(3)
                    if self._stream_thread is None and not self._stop_event.is_set():
                        cid = getattr(self, "_current_call_id", None)
                        if cid:
                            self.logger.info("[ASR_RECOVERY] Restarting ASR stream worker for call_id=%s", cid)
                            try:
                                self._start_stream_worker(cid)
                            except Exception as recover_err:  # pragma: no cover
                                self.logger.exception(
                                    "[ASR_RECOVERY] Failed to restart ASR stream worker: %s",
                                    recover_err,
                                )

                recovery_thread = threading.Thread(target=_recover_stream_worker, daemon=True)
                recovery_thread.start()
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
        if len(self._pre_stream_buffer) == 0:
            return
        buffer_copy = bytes(self._pre_stream_buffer)
        self._pre_stream_buffer.clear()
        try:
            self._q.put_nowait(buffer_copy)
            self.logger.info(
                "GoogleASR: PRE_STREAM_BUFFER_FLUSHED: len=%d bytes",
                len(buffer_copy),
            )
        except queue.Full:
            self.logger.warning(
                "GoogleASR: PRE_STREAM_BUFFER_FLUSH_FAILED (queue full): len=%d bytes",
                len(buffer_copy),
            )
        except Exception as exc:  # pragma: no cover
            self.logger.warning("GoogleASR: PRE_STREAM_BUFFER_FLUSH_ERROR: %s", exc)

    def feed_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        print(
            f"[FEED_AUDIO_ENTRY] call_id={call_id} len={len(pcm16k_bytes) if pcm16k_bytes else 0}",
            flush=True,
        )
        if not pcm16k_bytes or len(pcm16k_bytes) == 0:
            return
        if self._stop_event.is_set():
            print(f"[FEED_AUDIO_SKIP_STOP] call_id={call_id} _stop_event is set", flush=True)
            self.logger.debug("[FEED_AUDIO_SKIP] call_id=%s stopped, skipping feed_audio", call_id)
            return
        stream_running = self._stream_thread is not None and self._stream_thread.is_alive()
        print(
            "[FEED_AUDIO_STREAM_CHECK] call_id=%s stream_running=%s thread=%s alive=%s"
            % (
                call_id,
                stream_running,
                self._stream_thread is not None,
                self._stream_thread.is_alive() if self._stream_thread else False,
            ),
            flush=True,
        )
        self.logger.debug(
            "[FEED_AUDIO] call_id=%s chunk=%dB stream=%s", call_id, len(pcm16k_bytes), stream_running
        )
        try:
            import audioop

            rms = audioop.rms(pcm16k_bytes, 2)
            self.logger.info(
                "[STREAMING_FEED] call_id=%s len=%d bytes rms=%s",
                call_id,
                len(pcm16k_bytes),
                rms,
            )
        except Exception as exc:  # pragma: no cover
            self.logger.debug("[STREAMING_FEED] RMS calculation failed: %s", exc)

        if not stream_running:
            if len(self._pre_stream_buffer) < self._pre_stream_buffer_max_bytes:
                self._pre_stream_buffer.extend(pcm16k_bytes)
                self.logger.debug(
                    "GoogleASR: PRE_STREAM_BUFFER: call_id=%s len=%d bytes (total=%d)",
                    call_id,
                    len(pcm16k_bytes),
                    len(self._pre_stream_buffer),
                )
            else:
                self.logger.warning(
                    "GoogleASR: PRE_STREAM_BUFFER_FULL: forcing stream start (call_id=%s)",
                    call_id,
                )
                self._start_stream_worker(call_id)
                self._flush_pre_stream_buffer()
                stream_running = True

        if not stream_running:
            self._start_stream_worker(call_id)

        if len(self._debug_raw) < self._debug_max_bytes:
            remain = self._debug_max_bytes - len(self._debug_raw)
            self._debug_raw.extend(pcm16k_bytes[:remain])

        print(
            f"[FEED_AUDIO_QUEUE_BEFORE] call_id={call_id} queue_size={self._q.qsize()}",
            flush=True,
        )
        try:
            self._q.put_nowait(pcm16k_bytes)
            print(
                f"[FEED_AUDIO_QUEUE_SUCCESS] call_id={call_id} len={len(pcm16k_bytes)} queue_size={self._q.qsize()}",
                flush=True,
            )
            self.logger.info(
                "GoogleASR: QUEUE_PUT: call_id=%s len=%d bytes",
                call_id,
                len(pcm16k_bytes),
            )
        except queue.Full:
            print(
                f"[FEED_AUDIO_QUEUE_FULL] call_id={call_id} len={len(pcm16k_bytes)}",
                flush=True,
            )
            self.logger.warning(
                "GoogleASR: QUEUE_FULL (skipping chunk): call_id=%s len=%d bytes",
                call_id,
                len(pcm16k_bytes),
            )
        except Exception as exc:  # pragma: no cover
            print(
                f"[FEED_AUDIO_QUEUE_ERROR] call_id={call_id} error={exc}",
                flush=True,
            )
            self.logger.warning(
                "GoogleASR: QUEUE_PUT error (call_id=%s): %s",
                call_id,
                exc,
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
