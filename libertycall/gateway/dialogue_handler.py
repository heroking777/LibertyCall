"""Dialogue entrypoints and ASR error handling extracted from AICore."""

from __future__ import annotations

from typing import Optional, Tuple, List

from .state_store import get_session_state
from .prompt_factory import render_templates


def process_dialogue(core, pcm16k_bytes: bytes):
    if not core._wav_saved:
        core._save_debug_wav(pcm16k_bytes)

    text = core.asr_model.transcribe_pcm16(pcm16k_bytes)  # type: ignore[union-attr]
    core.logger.info("ASR Result: '%s'", text)

    if core._is_hallucination(text):
        core.logger.debug(">> Ignored hallucination (noise)")
        return None, False, text, "IGNORE", ""

    state_key = core.call_id or "BATCH_CALL"
    resp_text, template_ids, intent, transfer_requested = core._generate_reply(state_key, text)
    core.logger.info(
        "CONV_FLOW_BATCH: call_id=%s phase=%s intent=%s templates=%s",
        state_key,
        get_session_state(core, state_key).phase,
        intent,
        template_ids,
    )
    if transfer_requested:
        core._trigger_transfer(state_key)
    should_transfer = transfer_requested

    tts_audio = None
    if template_ids and core.use_gemini_tts:
        tts_audio = core._synthesize_template_sequence(template_ids)
        if not tts_audio:
            core.logger.debug("TTS synthesis failed for template_ids=%s", template_ids)
    elif not resp_text:
        core.logger.debug("No response text generated; skipping TTS synthesis.")
    else:
        core.logger.debug("TTS クライアント未初期化のため音声合成をスキップしました。")

    return tts_audio, should_transfer, text, intent, resp_text


def on_asr_error(core, call_id: str, error: Exception) -> None:
    error_type = type(error).__name__
    error_msg = str(error)
    core.logger.warning(
        "ASR_ERROR_HANDLER: call_id=%s error_type=%s error=%r",
        call_id,
        error_type,
        error_msg,
    )
    state = get_session_state(core, call_id)

    if state.handoff_state == "done" and state.transfer_requested:
        core.logger.info("ASR_ERROR_HANDLER: handoff already done (call_id=%s)", call_id)
        return

    is_permanent_error = any(
        keyword in error_msg.lower()
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

    if is_permanent_error:
        core.logger.error(
            "ASR_ERROR_HANDLER: permanent error detected (call_id=%s), skipping fallback speech. Error: %s",
            call_id,
            error_msg,
        )
        return

    fallback_text = "恐れ入ります。うまくお話をお伺いできませんでしたので、担当者におつなぎいたします。"

    state.handoff_state = "done"
    state.handoff_retry_count = 0
    state.handoff_prompt_sent = True
    state.transfer_requested = True
    core._trigger_transfer_if_needed(call_id, state)
    state.last_intent = "HANDOFF_ERROR_FALLBACK"

    if hasattr(core, "tts_callback") and core.tts_callback:  # type: ignore[attr-defined]
        try:
            template_ids = ["081", "082"]
            try:
                core.current_system_text = fallback_text or render_templates(template_ids) or ""
            except Exception:
                try:
                    core.current_system_text = fallback_text or ""
                except Exception:
                    core.current_system_text = ""
            core.tts_callback(call_id, fallback_text, template_ids, True)  # type: ignore[misc, attr-defined]
            core.logger.info(
                "ASR_ERROR_HANDLER: TTS fallback sent (call_id=%s, text=%s)",
                call_id,
                fallback_text,
            )
        except Exception as exc:
            core.logger.exception("ASR_ERROR_HANDLER: tts_callback error (call_id=%s): %s", call_id, exc)
    else:
        core.logger.warning(
            "ASR_ERROR_HANDLER: tts_callback not set (call_id=%s), transfer will proceed without fallback speech",
            call_id,
        )
