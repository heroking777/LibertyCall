"""Audio playback orchestration extracted from AICore."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional


def break_playback(core, call_id: str) -> None:
    if not core.esl_connection:
        core.logger.warning("[BREAK_PLAYBACK] ESL not available: call_id=%s", call_id)
        return

    if not core.esl_connection.connected():
        core.logger.warning("[BREAK_PLAYBACK] ESL not connected: call_id=%s", call_id)
        return

    def _break_playback_async() -> None:
        try:
            result = core.esl_connection.bgapi("uuid_break", call_id)
            if result:
                reply_text = result.getHeader("Reply-Text") if hasattr(result, "getHeader") else None
                if reply_text and "+OK" in reply_text:
                    core.logger.info("[BREAK_PLAYBACK] Playback interrupted: call_id=%s", call_id)
                else:
                    core.logger.debug(
                        "[BREAK_PLAYBACK] Break command sent (async): call_id=%s reply=%s",
                        call_id,
                        reply_text,
                    )
            else:
                core.logger.debug("[BREAK_PLAYBACK] Break command sent (async): call_id=%s", call_id)
        except Exception as exc:
            core.logger.exception(
                "[BREAK_PLAYBACK] Failed to break playback: call_id=%s error=%s",
                call_id,
                exc,
            )

    import threading

    thread = threading.Thread(target=_break_playback_async, daemon=True)
    thread.start()
    core.logger.debug("[BREAK_PLAYBACK] Break command queued (async): call_id=%s", call_id)


def play_audio_response(core, call_id: str, intent: str) -> None:
    audio_files = {
        "YES": "/opt/libertycall/clients/000/audio/yes_8k.wav",
        "NO": "/opt/libertycall/clients/000/audio/no_8k.wav",
        "OTHER": "/opt/libertycall/clients/000/audio/repeat_8k.wav",
    }

    audio_file = audio_files.get(intent)
    if not audio_file:
        core.logger.warning("_play_audio_response: Unknown intent %s", intent)
        return

    if not Path(audio_file).exists():
        core.logger.warning("_play_audio_response: Audio file not found: %s", audio_file)
        if intent == "YES":
            audio_file = "/opt/libertycall/clients/000/audio/110_8k.wav"
        elif intent == "NO":
            audio_file = "/opt/libertycall/clients/000/audio/111_8k.wav"
        else:
            audio_file = "/opt/libertycall/clients/000/audio/110_8k.wav"

    if hasattr(core, "playback_callback") and core.playback_callback:
        try:
            core.playback_callback(call_id, audio_file)
            core.logger.info(
                "[PLAYBACK] Sent audio playback request: call_id=%s file=%s",
                call_id,
                audio_file,
            )
        except Exception as exc:
            core.logger.exception("[PLAYBACK] Failed to send playback request: %s", exc)
    else:
        send_playback_request_http(core, call_id, audio_file)


def play_template_sequence(core, call_id: str, template_ids: List[str], client_id: Optional[str] = None) -> None:
    if not template_ids:
        return

    effective_client_id = client_id or core.call_client_map.get(call_id) or core.client_id or "000"

    if call_id not in core.last_template_play:
        core.last_template_play[call_id] = {}

    current_time = time.time()
    duplicate_prevention_sec = 10.0
    failed_templates = []

    try:
        try:
            combined_text = core._render_templates(template_ids) if template_ids else ""
        except Exception:
            combined_text = " ".join(template_ids) if template_ids else ""
        core.current_system_text = combined_text or ""
    except Exception:
        pass

    for template_id in template_ids:
        if call_id not in core.last_template_play:
            core.last_template_play[call_id] = {}

        last_play_time = core.last_template_play[call_id].get(template_id, 0)
        time_since_last_play = current_time - last_play_time

        if time_since_last_play < duplicate_prevention_sec and last_play_time > 0:
            core.logger.info(
                "[PLAY_TEMPLATE] Skipping recently played template: call_id=%s template_id=%s time_since_last=%.2fs",
                call_id,
                template_id,
                time_since_last_play,
            )
            continue

        audio_dir = Path(f"/opt/libertycall/clients/{effective_client_id}/audio")
        audio_file_plain = audio_dir / f"{template_id}.wav"
        audio_file_regular = audio_dir / f"{template_id}_8k.wav"
        audio_file_norm = audio_dir / f"{template_id}_8k_norm.wav"

        audio_file = None
        checked_paths = []
        for candidate in [audio_file_plain, audio_file_regular, audio_file_norm]:
            checked_paths.append(str(candidate))
            if candidate.exists():
                audio_file = str(candidate)
                core.logger.debug(
                    "[PLAY_TEMPLATE] Found audio file: template_id=%s file=%s",
                    template_id,
                    audio_file,
                )
                break

        if not audio_file:
            core.logger.warning(
                "[PLAY_TEMPLATE] Audio file not found: template_id=%s checked_paths=%s audio_dir=%s",
                template_id,
                checked_paths,
                audio_dir,
            )
            runtime_logger = logging.getLogger("runtime")
            runtime_logger.warning(
                "[FLOW] Missing template audio: call_id=%s template_id=%s",
                call_id,
                template_id,
            )
            fallback_template_id = "001"
            fallback_file = audio_dir / f"{fallback_template_id}.wav"
            if fallback_file.exists():
                audio_file = str(fallback_file)
                core.logger.info(
                    "[PLAY_TEMPLATE] Using fallback template: template_id=%s -> fallback=%s file=%s",
                    template_id,
                    fallback_template_id,
                    audio_file,
                )
            else:
                core.logger.error(
                    "[PLAY_TEMPLATE] Fallback template also not found: %s",
                    fallback_file,
                )
                continue

        if hasattr(core, "playback_callback") and core.playback_callback:
            try:
                core.playback_callback(call_id, audio_file)
                core.last_template_play[call_id][template_id] = current_time
                core.logger.info(
                    "[PLAY_TEMPLATE] Sent playback request (immediate): call_id=%s template_id=%s file=%s",
                    call_id,
                    template_id,
                    audio_file,
                )
            except Exception as exc:
                core.logger.exception(
                    "[PLAY_TEMPLATE] Failed to send playback request: call_id=%s template_id=%s error=%s",
                    call_id,
                    template_id,
                    exc,
                )
                failed_templates.append((template_id, audio_file))
        else:
            try:
                send_playback_request_http(core, call_id, audio_file)
            except Exception as exc:
                core.logger.exception(
                    "[PLAY_TEMPLATE] HTTP playback request failed: call_id=%s template_id=%s error=%s",
                    call_id,
                    template_id,
                    exc,
                )
                failed_templates.append((template_id, audio_file))

    if failed_templates:
        core.logger.info(
            "[PLAY_TEMPLATE] Retrying %s failed templates after UUID update: call_id=%s",
            len(failed_templates),
            call_id,
        )
        time.sleep(0.1)

        for template_id, audio_file in failed_templates:
            if hasattr(core, "playback_callback") and core.playback_callback:
                try:
                    core.playback_callback(call_id, audio_file)
                    core.last_template_play[call_id][template_id] = time.time()
                    core.logger.info(
                        "[PLAY_TEMPLATE] Retry successful: call_id=%s template_id=%s file=%s",
                        call_id,
                        template_id,
                        audio_file,
                    )
                except Exception as exc:
                    core.logger.error(
                        "[PLAY_TEMPLATE] Retry failed: call_id=%s template_id=%s error=%s",
                        call_id,
                        template_id,
                        exc,
                    )


def send_playback_request_http(core, call_id: str, audio_file: str) -> None:
    try:
        import requests  # noqa: F401

        core.logger.warning(
            "[PLAYBACK] HTTP API not implemented yet. "
            "Please use playback_callback or implement ESL connection. "
            "call_id=%s file=%s",
            call_id,
            audio_file,
        )
    except ImportError:
        core.logger.error("[PLAYBACK] requests module not available")
    except Exception as exc:
        core.logger.exception("[PLAYBACK] Failed to send HTTP request: %s", exc)
