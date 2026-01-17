"""Call lifecycle management extracted from AICore."""

from __future__ import annotations

import threading
import time
from typing import Optional

from .call_cleanup_helper import clear_auto_hangup_timer, run_call_end_cleanup
from .call_session_store import (
    get_call_metadata,
    mark_call_started,
    mark_intro_played,
    remove_call_tracking,
    set_call_client_meta,
)
from .call_status_logger import (
    log_call_end,
    log_call_start_entry,
    log_call_start_proceeding,
    log_call_start_skipped,
    log_duplicate_call_start,
    log_existing_active_session,
    log_intro_error,
    log_intro_missing_tts,
    log_intro_phase_entry,
    log_intro_phase_start,
    log_intro_queued,
    log_intro_sent,
    log_intro_tts_callback_set,
    log_phase_entry,
)
from .state_logic import ConversationState
from .state_store import get_session_state
from ..dialogue.prompt_factory import render_templates


def on_call_end(core, call_id: Optional[str], source: str = "unknown") -> None:
    if not call_id:
        return

    phase_at_end, client_id_from_state = get_call_metadata(core, call_id)
    effective_client_id = client_id_from_state or core.client_id or "000"

    was_started, was_intro_played = remove_call_tracking(core, call_id)

    log_call_end(
        core.logger,
        call_id,
        source,
        effective_client_id,
        phase_at_end,
        was_started,
        was_intro_played,
    )

    run_call_end_cleanup(core, call_id)


def trigger_transfer(core, call_id: str) -> None:
    core.logger.info("TRANSFER_TRIGGER_START: call_id=%s", call_id)
    if hasattr(core, "transfer_callback") and core.transfer_callback:
        try:
            core.logger.info("TRANSFER_TRIGGER: calling transfer_callback call_id=%s", call_id)
            core.transfer_callback(call_id)
            core.logger.info("TRANSFER_TRIGGER_DONE: transfer_callback completed call_id=%s", call_id)
        except Exception as exc:
            core.logger.exception(
                "TRANSFER_TRIGGER_ERROR: transfer_callback error call_id=%s error=%r",
                call_id,
                exc,
            )
    else:
        core.logger.warning(
            "TRANSFER_TRIGGER_SKIP: transfer requested but no callback is set call_id=%s",
            call_id,
        )


def trigger_transfer_if_needed(core, call_id: str, state: ConversationState) -> None:
    if not getattr(core, "transfer_callback", None):
        return

    if state.transfer_executed:
        return

    if not state.transfer_requested:
        return

    try:
        core.logger.info(
            "AICore: TRIGGER_TRANSFER call_id=%s phase=%s handoff_state=%s",
            call_id,
            state.phase,
            state.handoff_state,
        )
        core.transfer_callback(call_id)  # type: ignore[misc]
        state.transfer_executed = True
    except Exception:
        core.logger.exception("AICore: transfer_callback failed call_id=%s", call_id)


def schedule_auto_hangup(core, call_id: str, delay_sec: float = 60.0) -> None:
    key = call_id or "GLOBAL_CALL"

    core.logger.info(
        "AUTO_HANGUP_SCHEDULE_REQUEST: call_id=%s delay=%.1f hangup_cb=%s",
        key,
        delay_sec,
        "set" if core.hangup_callback else "none",
    )

    if not core.hangup_callback:
        core.logger.warning(
            "AUTO_HANGUP_SKIP: call_id=%s reason=no_hangup_callback",
            key,
        )
        return

    old_timer = core._auto_hangup_timers.get(key)
    if old_timer is not None:
        try:
            old_timer.cancel()
            core.logger.info("AUTO_HANGUP_CANCEL_PREV: call_id=%s", key)
        except Exception as exc:
            core.logger.warning(
                "AUTO_HANGUP_CANCEL_PREV_ERROR: call_id=%s error=%r",
                key,
                exc,
            )

    def _do_hangup() -> None:
        core.logger.info("AUTO_HANGUP_TRIGGER: call_id=%s", key)
        try:
            if core.hangup_callback:
                core.hangup_callback(key)
        except Exception as exc:
            core.logger.exception(
                "AUTO_HANGUP_CALLBACK_ERROR: call_id=%s error=%r",
                key,
                exc,
            )
        finally:
            try:
                core._auto_hangup_timers.pop(key, None)
            except Exception:
                pass

    timer = threading.Timer(delay_sec, _do_hangup)
    timer.daemon = True
    core._auto_hangup_timers[key] = timer
    timer.start()

    core.logger.info(
        "AUTO_HANGUP_SCHEDULED: call_id=%s delay=%.1f",
        key,
        delay_sec,
    )


def on_call_start(core, call_id: str, client_id: str = None, **kwargs) -> None:
    try:
        current_time = time.time()
        last_time = getattr(core, "last_start_times", {}).get(call_id, 0)
        if (current_time - last_time) < 2.0:
            log_duplicate_call_start(core.logger, call_id)
            return
        try:
            if not hasattr(core, "last_start_times"):
                core.last_start_times = {}
            core.last_start_times[call_id] = current_time
        except Exception:
            pass
    except Exception:
        pass

    effective_client_id = client_id or core.client_id or "000"

    try:
        active_found = False
        if hasattr(core, "active_calls") and call_id in getattr(core, "active_calls"):
            active_found = True
        elif (
            hasattr(core, "gateway")
            and hasattr(core.gateway, "_active_calls")
            and call_id in getattr(core.gateway, "_active_calls")
        ):
            active_found = True
        if active_found:
            log_existing_active_session(core.logger, call_id)
            try:
                core.cleanup_call(call_id)
            except Exception as exc:
                core.logger.exception("[CLEANUP] cleanup_call error for %s: %s", call_id, exc)
    except Exception:
        pass

    log_call_start_entry(core.logger, call_id, effective_client_id)

    if call_id in core._call_started_calls:
        log_call_start_skipped(core.logger, call_id)
        return

    log_call_start_proceeding(
        core.logger,
        call_id,
        effective_client_id,
        core.client_id,
    )
    mark_call_started(core, call_id)

    set_call_client_meta(core, call_id, effective_client_id)

    if effective_client_id == "001":
        state = get_session_state(core, call_id)
        state.phase = "INTRO"
        log_intro_phase_start(core.logger, call_id)
        if hasattr(core, "tts_callback") and core.tts_callback:
            log_intro_tts_callback_set()
            try:
                log_intro_queued(core.logger, call_id)
                try:
                    try:
                        core.current_system_text = render_templates(["000-002"]) or ""
                    except Exception:
                        core.current_system_text = "000-002"
                except Exception:
                    pass
                core.tts_callback(call_id, None, ["000-002"], False)  # type: ignore[misc, attr-defined]
                mark_intro_played(core, call_id)
                log_intro_sent(core.logger, call_id)

                state = get_session_state(core, call_id)
                state.phase = "ENTRY"
                log_intro_phase_entry(core.logger, call_id)

            except Exception as exc:
                log_intro_error(core.logger, call_id, exc)
                state = get_session_state(core, call_id)
                state.phase = "ENTRY"
        else:
            log_intro_missing_tts(call_id, core.logger)
            state = get_session_state(core, call_id)
            state.phase = "ENTRY"
    else:
        state = get_session_state(core, call_id)
        state.phase = "ENTRY"
        log_phase_entry(core.logger, call_id, effective_client_id)


def reset_call(core, call_id: str) -> None:
    core._call_started_calls.discard(call_id)
    core.logger.info("[CLEANUP] Removed call_id=%s from _call_started_calls", call_id)

    if core.streaming_enabled and core.asr_model is not None:
        if core.asr_provider == "google":
            try:
                core.logger.info("[CLEANUP] Calling end_stream for call_id=%s", call_id)
                core.asr_model.end_stream(call_id)  # type: ignore[union-attr]
                core.logger.info("[CLEANUP] end_stream completed for call_id=%s", call_id)
            except Exception as exc:
                core.logger.error(
                    "[CLEANUP] GoogleASR end_stream failed for call_id=%s: %s",
                    call_id,
                    exc,
                    exc_info=True,
                )
        core.asr_model.reset_call(call_id)  # type: ignore[union-attr]
    core._reset_session_state(call_id)
    if call_id in core.partial_transcripts:
        del core.partial_transcripts[call_id]

    clear_auto_hangup_timer(core, call_id)
