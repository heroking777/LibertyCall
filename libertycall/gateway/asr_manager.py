"""ASR streaming handlers extracted from AICore."""

from __future__ import annotations

import threading
import time
import traceback

from .google_asr import GoogleASR


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
