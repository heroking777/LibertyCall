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
