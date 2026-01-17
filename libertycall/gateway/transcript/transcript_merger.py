"""Transcript merge helpers for ASR partial/final handling."""
from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

from ..dialogue.prompt_factory import render_templates
from .transcript_file_manager import TranscriptFileManager


def merge_transcript(
    core,
    call_id: str,
    text: str,
    is_final: bool,
    file_manager: TranscriptFileManager,
    logger: logging.Logger,
) -> Tuple[Optional[str], Optional[str], bool]:
    if not is_final:
        file_manager.ensure_partial_entry(call_id)
        if text:
            file_manager.update_partial(call_id, text)

        merged_text = file_manager.get_partial_text(call_id)
        logger.debug("[ASR_PARTIAL] call_id=%s partial=%r", call_id, merged_text)

        text_stripped = text.strip() if text else ""
        if 1 <= len(text_stripped) <= 6:
            backchannel_keywords = ["はい", "えっと", "あの", "ええ", "そう", "うん", "ああ"]
            if any(keyword in text_stripped for keyword in backchannel_keywords):
                logger.debug(
                    "[BACKCHANNEL_TRIGGER] Detected short utterance: %s", text_stripped
                )
                if hasattr(core, "tts_callback") and core.tts_callback:  # type: ignore[attr-defined]
                    try:
                        try:
                            core.current_system_text = "はい"
                        except Exception:
                            pass
                        core.tts_callback(call_id, "はい", None, False)  # type: ignore[misc]
                        logger.info(
                            "[BACKCHANNEL_SENT] call_id=%s text='はい' (triggered by partial)",
                            call_id,
                        )
                    except Exception as exc:
                        logger.exception(
                            "[BACKCHANNEL_ERROR] call_id=%s error=%s", call_id, exc
                        )

        merged_text = file_manager.get_partial_text(call_id)
        text_stripped = merged_text.strip() if merged_text else ""
        is_greeting_detected = file_manager.greeting_detected(text_stripped)

        if file_manager.should_process_partial(merged_text, is_greeting_detected):
            if file_manager.is_partial_processed(call_id):
                logger.debug(
                    "[ASR_SKIP_PARTIAL] Already processed: call_id=%s text=%r",
                    call_id,
                    merged_text,
                )
                return None, None, True

            file_manager.mark_partial_processed(call_id)
            logger.info(
                "[ASR_DEBUG_PARTIAL] call_id=%s partial_data_after_processed=%s",
                call_id,
                core.partial_transcripts[call_id],
            )
            if is_greeting_detected:
                logger.info(
                    "[ASR_PARTIAL_PROCESS] call_id=%s partial_text=%r (GREETING)",
                    call_id,
                    merged_text,
                )
            else:
                logger.info(
                    "[ASR_PARTIAL_PROCESS] call_id=%s partial_text=%r",
                    call_id,
                    merged_text,
                )
        else:
            return None, None, True

    partial_text = ""
    if is_final:
        if file_manager.should_skip_final(call_id, text):
            return None, None, True

        partial_text, _ = file_manager.merge_final(call_id, text)

    file_manager.update_last_activity(call_id)

    if core.is_playing.get(call_id, False):
        logger.info(
            "[PLAYBACK_INTERRUPT] call_id=%s text=%r -> executing uuid_break (async)",
            call_id,
            text,
        )
        core._break_playback(call_id)
        core.is_playing[call_id] = False
        runtime_logger = logging.getLogger("runtime")
        runtime_logger.info("UUID_BREAK call_id=%s text=%s", call_id, text[:50])
        time.sleep(0.05)

    merged_text = text if text else partial_text

    logger.info(
        "[ASR_FINAL] call_id=%s partial=%r final=%r merged=%r",
        call_id,
        partial_text,
        text,
        merged_text,
    )

    if len(merged_text) < 2:
        if len(merged_text) == 1:
            ambiguous_chars = ["あ", "ん", "え", "お", "う", "い"]
            if merged_text in ambiguous_chars:
                logger.debug(
                    "[ASR_AMBIGUOUS] call_id=%s text=%r -> treating as NOT_HEARD",
                    call_id,
                    merged_text,
                )
                intent = "NOT_HEARD"
                template_ids = ["110"]
                reply_text = render_templates(template_ids)
                if hasattr(core, "tts_callback") and core.tts_callback:  # type: ignore[attr-defined]
                    try:
                        try:
                            core.current_system_text = (
                                reply_text or render_templates(template_ids) or ""
                            )
                        except Exception:
                            core.current_system_text = reply_text or ""
                        core.tts_callback(call_id, reply_text, template_ids, False)  # type: ignore[misc]
                        logger.info(
                            "TTS_SENT: call_id=%s templates=%s (NOT_HEARD for ambiguous 1-char)",
                            call_id,
                            template_ids,
                        )
                    except Exception as exc:
                        logger.exception(
                            "TTS_ERROR: call_id=%s error=%s",
                            call_id,
                            exc,
                        )
                return None, reply_text, True
        logger.debug(
            "[ASR_SHORT] call_id=%s text=%r len=%s -> skipping (too short)",
            call_id,
            merged_text,
            len(merged_text),
        )
        return None, None, True

    return merged_text, None, False
