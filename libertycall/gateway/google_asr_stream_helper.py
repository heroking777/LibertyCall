"""Streaming helper utilities for Google ASR."""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import Callable, Iterable, Optional

from .google_asr_config import cloud_speech

KEEPALIVE_EMPTY_CHUNK_INTERVAL = 10
QUEUE_GET_TIMEOUT_SEC = 0.1


class StreamRecoveryPolicy:
    def __init__(self, base_delay_sec: float = 3.0, max_delay_sec: float = 15.0) -> None:
        self.base_delay_sec = base_delay_sec
        self.max_delay_sec = max_delay_sec
        self._attempt = 0

    def next_delay(self) -> float:
        delay = min(self.base_delay_sec * (2**self._attempt), self.max_delay_sec)
        self._attempt += 1
        return delay

    def reset(self) -> None:
        self._attempt = 0


def build_request_generator(
    audio_queue: "queue.Queue[bytes]",
    stop_event: threading.Event,
    logger: logging.Logger,
    call_id_getter: Callable[[], str],
    keepalive_interval: int = KEEPALIVE_EMPTY_CHUNK_INTERVAL,
    queue_timeout_sec: float = QUEUE_GET_TIMEOUT_SEC,
) -> Iterable["cloud_speech.StreamingRecognizeRequest"]:
    logger.warning(
        "[REQUEST_GEN_ENTRY] Generator START for call_id=%s",
        call_id_getter(),
    )
    print(
        f"[REQUEST_GEN_ENTRY] Generator START for call_id={call_id_getter()}",
        flush=True,
    )

    empty_count = 0
    while not stop_event.is_set():
        try:
            chunk = audio_queue.get(timeout=queue_timeout_sec)
            if chunk is None:
                logger.info("[REQUEST_GEN] Received sentinel (None), stopping generator")
                return
            logger.warning("[REQUEST_GEN_DATA] Got chunk from queue, size=%d", len(chunk))
            print(
                f"[REQUEST_GEN_DATA] Got chunk from queue, size={len(chunk)}",
                flush=True,
            )
            empty_count = 0
        except queue.Empty:
            if stop_event.is_set():
                break
            empty_count += 1
            if empty_count >= keepalive_interval:
                empty_count = 0
                logger.debug("[ASR_GEN] Emitting keepalive empty audio chunk")
                yield cloud_speech.StreamingRecognizeRequest(audio_content=b"")  # type: ignore[arg-type]
            continue

        if not isinstance(chunk, bytes) or len(chunk) == 0:
            continue
        logger.debug("[ASR_GEN] Yielding audio request")
        yield cloud_speech.StreamingRecognizeRequest(audio_content=chunk)  # type: ignore[arg-type]


def schedule_stream_recovery(
    policy: StreamRecoveryPolicy,
    start_stream_worker: Callable[[str], None],
    stop_event: threading.Event,
    logger: logging.Logger,
    call_id: Optional[str],
) -> None:
    if not call_id:
        return
    delay = policy.next_delay()
    logger.info(
        "[ASR_RECOVERY] Scheduling restart for call_id=%s in %.1fs",
        call_id,
        delay,
    )

    def _recover_stream_worker() -> None:
        time.sleep(delay)
        if stop_event.is_set():
            return
        logger.info("[ASR_RECOVERY] Restarting ASR stream worker for call_id=%s", call_id)
        try:
            start_stream_worker(call_id)
        except Exception as recover_err:  # pragma: no cover
            logger.exception(
                "[ASR_RECOVERY] Failed to restart ASR stream worker: %s",
                recover_err,
            )

    recovery_thread = threading.Thread(target=_recover_stream_worker, daemon=True)
    recovery_thread.start()


def flush_pre_stream_buffer(
    pre_stream_buffer: bytearray,
    audio_queue: "queue.Queue[bytes]",
    logger: logging.Logger,
) -> None:
    if len(pre_stream_buffer) == 0:
        return
    buffer_copy = bytes(pre_stream_buffer)
    pre_stream_buffer.clear()
    try:
        audio_queue.put_nowait(buffer_copy)
        logger.info(
            "GoogleASR: PRE_STREAM_BUFFER_FLUSHED: len=%d bytes",
            len(buffer_copy),
        )
    except queue.Full:
        logger.warning(
            "GoogleASR: PRE_STREAM_BUFFER_FLUSH_FAILED (queue full): len=%d bytes",
            len(buffer_copy),
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("GoogleASR: PRE_STREAM_BUFFER_FLUSH_ERROR: %s", exc)


def feed_audio_chunk(
    call_id: str,
    pcm16k_bytes: bytes,
    *,
    stop_event: threading.Event,
    stream_thread_getter: Callable[[], Optional[threading.Thread]],
    pre_stream_buffer: bytearray,
    pre_stream_buffer_max_bytes: int,
    debug_raw: bytearray,
    debug_max_bytes: int,
    audio_queue: "queue.Queue[bytes]",
    start_stream_worker: Callable[[str], None],
    logger: logging.Logger,
    flush_buffer: Callable[[], None],
) -> None:
    print(
        f"[FEED_AUDIO_ENTRY] call_id={call_id} len={len(pcm16k_bytes) if pcm16k_bytes else 0}",
        flush=True,
    )
    if not pcm16k_bytes or len(pcm16k_bytes) == 0:
        return
    if stop_event.is_set():
        print(f"[FEED_AUDIO_SKIP_STOP] call_id={call_id} _stop_event is set", flush=True)
        logger.debug("[FEED_AUDIO_SKIP] call_id=%s stopped, skipping feed_audio", call_id)
        return

    stream_thread = stream_thread_getter()
    stream_running = stream_thread is not None and stream_thread.is_alive()
    print(
        "[FEED_AUDIO_STREAM_CHECK] call_id=%s stream_running=%s thread=%s alive=%s"
        % (
            call_id,
            stream_running,
            stream_thread is not None,
            stream_thread.is_alive() if stream_thread else False,
        ),
        flush=True,
    )
    logger.debug(
        "[FEED_AUDIO] call_id=%s chunk=%dB stream=%s", call_id, len(pcm16k_bytes), stream_running
    )
    try:
        import audioop

        rms = audioop.rms(pcm16k_bytes, 2)
        logger.info(
            "[STREAMING_FEED] call_id=%s len=%d bytes rms=%s",
            call_id,
            len(pcm16k_bytes),
            rms,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("[STREAMING_FEED] RMS calculation failed: %s", exc)

    if not stream_running:
        if len(pre_stream_buffer) < pre_stream_buffer_max_bytes:
            pre_stream_buffer.extend(pcm16k_bytes)
            logger.debug(
                "GoogleASR: PRE_STREAM_BUFFER: call_id=%s len=%d bytes (total=%d)",
                call_id,
                len(pcm16k_bytes),
                len(pre_stream_buffer),
            )
        else:
            logger.warning(
                "GoogleASR: PRE_STREAM_BUFFER_FULL: forcing stream start (call_id=%s)",
                call_id,
            )
            start_stream_worker(call_id)
            flush_buffer()
            stream_running = True

    if not stream_running:
        start_stream_worker(call_id)

    if len(debug_raw) < debug_max_bytes:
        remain = debug_max_bytes - len(debug_raw)
        debug_raw.extend(pcm16k_bytes[:remain])

    print(
        f"[FEED_AUDIO_QUEUE_BEFORE] call_id={call_id} queue_size={audio_queue.qsize()}",
        flush=True,
    )
    try:
        audio_queue.put_nowait(pcm16k_bytes)
        print(
            f"[FEED_AUDIO_QUEUE_SUCCESS] call_id={call_id} len={len(pcm16k_bytes)} queue_size={audio_queue.qsize()}",
            flush=True,
        )
        logger.info(
            "GoogleASR: QUEUE_PUT: call_id=%s len=%d bytes",
            call_id,
            len(pcm16k_bytes),
        )
    except queue.Full:
        print(
            f"[FEED_AUDIO_QUEUE_FULL] call_id={call_id} len={len(pcm16k_bytes)}",
            flush=True,
        )
        logger.warning(
            "GoogleASR: QUEUE_FULL (skipping chunk): call_id=%s len=%d bytes",
            call_id,
            len(pcm16k_bytes),
        )
    except Exception as exc:  # pragma: no cover
        print(
            f"[FEED_AUDIO_QUEUE_ERROR] call_id={call_id} error={exc}",
            flush=True,
        )
        logger.warning(
            "GoogleASR: QUEUE_PUT error (call_id=%s): %s",
            call_id,
            exc,
        )


def handle_streaming_responses(
    responses,
    *,
    logger: logging.Logger,
    ai_core,
    current_call_id: Callable[[], str],
    stream_start_time: Callable[[], Optional[float]],
    restart_flag_getter: Callable[[], bool],
    restart_flag_reset: Callable[[], None],
) -> None:
    for response in responses:
        results_count = len(response.results) if response.results else 0
        error_code = response.error.code if response.error else None
        logger.warning(
            "[ASR_RESPONSE_RECEIVED] results=%s, error_code=%s",
            results_count,
            error_code,
        )

        start_time = stream_start_time()
        if start_time and time.time() - start_time >= 280.0:
            call_id = current_call_id() or "TEMP_CALL"
            logger.warning(
                "[ASR_AUTO_RESTART] Stream duration limit approaching for call_id=%s",
                call_id,
            )

        logger.info("GoogleASR: STREAM_RESPONSE: %s", response)
        for result in response.results:
            if not result.alternatives:
                continue
            alt = result.alternatives[0]
            transcript = alt.transcript
            is_final = result.is_final
            confidence = alt.confidence if getattr(alt, "confidence", 0.0) else 0.0

            logger.debug(
                "[ASR_DEBUG] google_raw call_id=%s is_final=%s transcript=%r confidence=%s",
                current_call_id() or "TEMP_CALL",
                is_final,
                transcript,
                confidence if confidence else None,
            )
            logger.info(
                "GoogleASR: ASR_GOOGLE_RAW: final=%s conf=%.3f text=%s",
                is_final,
                confidence,
                transcript,
            )
            if ai_core:
                try:
                    call_id = current_call_id() or "TEMP_CALL"
                    if not is_final:
                        text_stripped = transcript.strip() if transcript else ""
                        if 1 <= len(text_stripped) <= 6:
                            backchannel_keywords = [
                                "はい",
                                "えっと",
                                "あの",
                                "ええ",
                                "そう",
                                "うん",
                                "ああ",
                            ]
                            if any(keyword in text_stripped for keyword in backchannel_keywords):
                                logger.debug(
                                    "[BACKCHANNEL_TRIGGER_ASR] Detected short utterance: %s",
                                    text_stripped,
                                )
                                if hasattr(ai_core, "tts_callback") and ai_core.tts_callback:  # type: ignore[attr-defined]
                                    try:
                                        try:
                                            loop = asyncio.get_event_loop()
                                            loop.create_task(
                                                asyncio.to_thread(
                                                    ai_core.tts_callback,  # type: ignore[misc]
                                                    call_id,
                                                    "はい",
                                                    None,
                                                    False,
                                                )
                                            )
                                        except RuntimeError:
                                            ai_core.tts_callback(call_id, "はい", None, False)  # type: ignore[misc]
                                        logger.info(
                                            "[BACKCHANNEL_SENT_ASR] call_id=%s text='はい'",
                                            call_id,
                                        )
                                    except Exception as err:  # pragma: no cover
                                        logger.exception(
                                            "[BACKCHANNEL_ERROR_ASR] call_id=%s error=%s",
                                            call_id,
                                            err,
                                        )
                    ai_core.on_transcript(call_id, transcript, is_final=is_final)
                except Exception as err:  # pragma: no cover
                    logger.exception("GoogleASR: on_transcript 呼び出しエラー: %s", err)

            if is_final:
                logger.info(
                    "GoogleASR: ASR_GOOGLE_FINAL: conf=%.3f text=%s",
                    confidence,
                    transcript,
                )
                logger.info('[ASR_RESULT] "%s"', transcript)

    if restart_flag_getter():
        call_id = current_call_id() or "TEMP_CALL"
        logger.info(
            "[ASR_AUTO_RESTART] Scheduled restart suppressed for call_id=%s",
            call_id,
        )
        restart_flag_reset()
