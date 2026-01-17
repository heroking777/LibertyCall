"""Transcript handling logic extracted from AICore."""

from __future__ import annotations

import logging
import time
from typing import Optional

from .prompt_factory import render_templates
from .text_utils import normalize_text
from .state_store import get_session_state
from .transcript_db_client import save_transcript_event, append_user_call_log, reset_no_input_streak
from .transcript_file_manager import TranscriptFileManager
from .transcript_notifier import notify_event
from .intent_classifier import classify_simple_intent
from .audio_orchestrator import play_audio_response


def handle_transcript(
    core,
    call_id: str,
    text: str,
    is_final: bool = True,
    **kwargs,
) -> Optional[str]:
    """Handle ASR transcript and drive dialogue flow."""
    logger = core.logger if hasattr(core, "logger") else logging.getLogger(__name__)
    file_manager = TranscriptFileManager(core, logger)

    if is_final:
        logger.info("[ASR_TRANSCRIPT] call_id=%s is_final=True text=%r", call_id, text)
    else:
        logger.debug("[ASR_TRANSCRIPT] call_id=%s is_final=False text=%r", call_id, text)

    try:
        text_preview = text if isinstance(text, str) else repr(text)
    except Exception:
        text_preview = "<unrepresentable>"
    logger.info(
        "[TRANSCRIPT_DEBUG] Received text=%r, is_final=%s for call_id=%s",
        text_preview,
        is_final,
        call_id,
    )

    file_manager.update_system_text_on_playback(call_id)
    if file_manager.ignore_system_echo(text):
        return None

    if not text or len(text.strip()) == 0:
        logger.debug("[ASR_TRANSCRIPT] Empty text, skipping: call_id=%s", call_id)
        return None

    save_transcript_event(core, call_id, text, is_final, kwargs, logger)
    notify_event(logger, "ASR_TRANSCRIPT", f"call_id={call_id} text={text[:50]}", call_id=call_id)

    file_manager.cleanup_stale_partials(max_age_sec=30.0)

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
                return None

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
            return None

    partial_text = ""

    if is_final:
        if file_manager.should_skip_final(call_id, text):
            return None

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
                return reply_text
        logger.debug(
            "[ASR_SHORT] call_id=%s text=%r len=%s -> skipping (too short)",
            call_id,
            merged_text,
            len(merged_text),
        )
        return None

    if merged_text:
        append_user_call_log(core, merged_text, logger)
        reset_no_input_streak(core, call_id, merged_text, logger)

    if not merged_text:
        return None

    if core._is_hallucination(merged_text):
        logger.debug(">> Ignored hallucination (noise)")
        return None

    logger.debug(
        "[ASR_DEBUG] merged_for_intent call_id=%s text=%r",
        call_id,
        merged_text,
    )

    state = get_session_state(core, call_id)
    phase_before = state.phase

    intent = None
    normalized = ""
    if merged_text:
        normalized = normalize_text(merged_text)
        intent = "UNKNOWN"
        logger.info("[INTENT] %s (deprecated)", intent)
        runtime_logger = logging.getLogger("runtime")
        runtime_logger.info(
            "INTENT call_id=%s intent=%s text=%s",
            call_id,
            intent,
            merged_text[:50],
        )

        simple_intent = classify_simple_intent(merged_text, normalized)
        if simple_intent:
            logger.info("[SIMPLE_INTENT] %s (text=%r)", simple_intent, merged_text)
            play_audio_response(core, call_id, simple_intent)
            return None

    flow_engine = core.flow_engines.get(call_id) or core.flow_engine
    if flow_engine:
        try:
            try:
                preview_for_flow = merged_text if isinstance(merged_text, str) else repr(merged_text)
            except Exception:
                preview_for_flow = "<unrepresentable>"
            logger.info(
                "[TRANSCRIPT_DEBUG] Passing text to FlowEngine for call_id=%s text=%r",
                call_id,
                preview_for_flow,
            )
            client_id = (
                core.call_client_map.get(call_id)
                or state.meta.get("client_id")
                or core.client_id
                or "000"
            )
            reply_text, template_ids, intent, transfer_requested = core._handle_flow_engine_transition(
                call_id,
                merged_text,
                normalized,
                intent,
                state,
                flow_engine,
                client_id,
            )
            phase_after = state.phase

            logger.info(
                "FLOW_ENGINE: call_id=%s client_id=%s phase=%s->%s intent=%s templates=%s transfer=%s",
                call_id,
                client_id,
                phase_before,
                phase_after,
                intent,
                template_ids,
                transfer_requested,
            )
            runtime_logger = logging.getLogger("runtime")
            template_str = ",".join(template_ids) if template_ids else "none"
            runtime_logger.info(
                "[FLOW] call_id=%s phase=%s→%s intent=%s template=%s",
                call_id,
                phase_before,
                phase_after,
                intent,
                template_str,
            )

            if template_ids:
                core._play_template_sequence(call_id, template_ids, client_id)

            if transfer_requested:
                core._trigger_transfer_if_needed(call_id, state)

            return reply_text
        except Exception as exc:
            logger.exception("[FLOW_ENGINE] Error in flow engine transition: %s", exc)
            logger.warning("[FLOW_ENGINE] Using fallback template due to error: call_id=%s", call_id)
            try:
                fallback_template_ids = ["110"]
                client_id = (
                    core.call_client_map.get(call_id)
                    or state.meta.get("client_id")
                    or core.client_id
                    or "000"
                )
                core._play_template_sequence(call_id, fallback_template_ids, client_id)
            except Exception as fallback_err:
                logger.exception(
                    "[FLOW_ENGINE] Failed to play fallback template: %s",
                    fallback_err,
                )

    if not merged_text or len(merged_text.strip()) == 0:
        no_input_streak = state.no_input_streak
        logger.info(
            "[NO_INPUT] call_id=%s streak=%s (empty text detected)",
            call_id,
            no_input_streak,
        )
        if no_input_streak == 1:
            template_ids = ["110"]
        elif no_input_streak == 2:
            template_ids = ["111"]
        else:
            template_ids = ["112"]
            if core.hangup_callback:
                logger.info(
                    "[NO_INPUT] call_id=%s template=112, scheduling auto_hangup delay=2.0s",
                    call_id,
                )
                try:
                    core._schedule_auto_hangup(call_id, delay_sec=2.0)
                except Exception as exc:
                    logger.exception(
                        "[NO_INPUT] AUTO_HANGUP_SCHEDULE_ERROR: call_id=%s error=%r",
                        call_id,
                        exc,
                    )

        reply_text = render_templates(template_ids)
        intent = "NOT_HEARD"
        transfer_requested = False
        state.last_ai_templates = template_ids
        caller_number = getattr(core, "caller_number", None) or "未設定"
        logger.info(
            "[NO_INPUT] call_id=%s caller=%s streak=%s template=%s",
            call_id,
            caller_number,
            no_input_streak,
            template_ids[0] if template_ids else "NONE",
        )
    else:
        reply_text, template_ids, intent, transfer_requested = core._generate_reply(
            call_id,
            merged_text,
        )

    phase_after = state.phase

    logger.info(
        "CONV_FLOW: call_id=%s phase=%s->%s intent=%s templates=%s transfer=%s",
        call_id,
        phase_before,
        phase_after,
        intent,
        template_ids,
        transfer_requested,
    )

    if phase_before != "END" and phase_after == "END" and not state.transfer_requested:
        logger.info("AUTO_HANGUP: scheduling for call_id=%s", call_id)
        core._schedule_auto_hangup(call_id, delay_sec=60.0)

    core._log_ai_templates(template_ids)

    if not reply_text:
        logger.debug(
            "No reply generated for call_id=%s (phase=%s)",
            call_id,
            phase_after,
        )
        if transfer_requested:
            core._trigger_transfer_if_needed(call_id, state)
        return None

    current_phase = state.phase
    if current_phase == "INTRO":
        logger.debug(
            "[AICORE] Phase=INTRO, skipping TTS (intro playing) call_id=%s templates=%s",
            call_id,
            template_ids,
        )
        if transfer_requested:
            core._trigger_transfer_if_needed(call_id, state)
        return reply_text

    if hasattr(core, "tts_callback") and core.tts_callback:  # type: ignore[attr-defined]
        try:
            try:
                core.current_system_text = (
                    reply_text or render_templates(template_ids) or ""
                )
            except Exception:
                core.current_system_text = reply_text or ""
            core.tts_callback(call_id, reply_text, template_ids, transfer_requested)  # type: ignore[misc]
            logger.info(
                "TTS_SENT: call_id=%s templates=%s transfer_requested=%s",
                call_id,
                template_ids,
                transfer_requested,
            )
        except Exception as exc:
            logger.exception("TTS_ERROR: call_id=%s error=%s", call_id, exc)

    return reply_text
