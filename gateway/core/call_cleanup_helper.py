"""Cleanup helpers for call lifecycle."""
from __future__ import annotations

from typing import Optional


def run_call_end_cleanup(core, call_id: str) -> None:
    core._save_session_summary(call_id)

    try:
        core.reset_call(call_id)
        core.logger.info("[CLEANUP] reset_call() executed for call_id=%s", call_id)
    except Exception as exc:
        core.logger.error(
            "[CLEANUP] Failed to reset_call(): call_id=%s error=%s",
            call_id,
            exc,
            exc_info=True,
        )

    try:
        core.cleanup_call(call_id)
        core.logger.info("[CLEANUP] cleanup_call() executed for call_id=%s", call_id)
    except Exception as exc:
        core.logger.debug("[CLEANUP] cleanup_call() failed for call_id=%s: %s", call_id, exc)


def clear_auto_hangup_timer(core, call_id: Optional[str]) -> None:
    key = call_id or "GLOBAL_CALL"
    timer = core._auto_hangup_timers.pop(key, None)
    if timer is not None:
        try:
            timer.cancel()
            core.logger.info("AUTO_HANGUP_TIMER_CANCELED: call_id=%s", key)
        except Exception as exc:
            core.logger.warning(
                "AUTO_HANGUP_TIMER_CANCEL_ERROR: call_id=%s error=%r",
                key,
                exc,
            )


def cleanup_gateway_call_state(gateway, call_id: str, logger=None) -> None:
    """通話終了時のgateway状態クリーンアップ（共通処理）"""
    if not call_id:
        return
    log = logger or getattr(gateway, "logger", None)

    if hasattr(gateway, "_active_calls") and call_id in gateway._active_calls:
        gateway._active_calls.discard(call_id)
        if log:
            log.info("[CALL_CLEANUP] Removed %s from _active_calls", call_id)

    for attr in ("_recovery_counts", "_last_processed_sequence"):
        mapping = getattr(gateway, attr, None)
        if mapping and call_id in mapping:
            del mapping[call_id]

    for attr in ("_last_voice_time", "_last_silence_time", "_last_tts_end_time",
                 "_last_user_input_time", "_silence_warning_sent"):
        mapping = getattr(gateway, attr, None)
        if mapping:
            mapping.pop(call_id, None)

    for attr in ("_initial_sequence_played", "_initial_tts_sent"):
        s = getattr(gateway, attr, None)
        if s and call_id in s:
            s.discard(call_id)

    if log:
        log.debug("[CALL_CLEANUP] Cleared state for call_id=%s", call_id)
