"""Call lifecycle management extracted from AICore."""

from __future__ import annotations

import threading
import time
from typing import Optional

from .state_logic import ConversationState
from .state_store import get_session_state


def on_call_end(core, call_id: Optional[str], source: str = "unknown") -> None:
    if not call_id:
        return

    try:
        state = get_session_state(core, call_id)
        phase_at_end = state.phase
        client_id_from_state = state.meta.get("client_id") if hasattr(state, "meta") and state.meta else None
    except Exception:
        phase_at_end = "unknown"
        client_id_from_state = None
    effective_client_id = client_id_from_state or core.client_id or "000"

    was_started = call_id in core._call_started_calls
    was_intro_played = call_id in core._intro_played_calls

    core._call_started_calls.discard(call_id)
    core._intro_played_calls.discard(call_id)

    core.last_activity.pop(call_id, None)

    cleanup_items = [
        ("last_activity", core.last_activity),
        ("is_playing", core.is_playing),
        ("partial_transcripts", core.partial_transcripts),
        ("last_template_play", core.last_template_play),
    ]

    for name, data_dict in cleanup_items:
        if call_id in data_dict:
            del data_dict[call_id]
            core.logger.info("[CLEANUP] Removed %s for call_id=%s", name, call_id)

    core.logger.info(
        "[AICORE] on_call_end() call_id=%s source=%s client_id=%s phase=%s "
        "_call_started_calls=%s _intro_played_calls=%s -> cleared",
        call_id,
        source,
        effective_client_id,
        phase_at_end,
        was_started,
        was_intro_played,
    )

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
            try:
                core.logger.warning("[CALL_START] Ignored duplicate start event for %s", call_id)
            except Exception:
                print(f"[CALL_START] Ignored duplicate start event for {call_id}", flush=True)
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
            core.logger.warning(
                "[CLEANUP] Found existing active session for %s at start. Forcing cleanup.",
                call_id,
            )
            try:
                core.cleanup_call(call_id)
            except Exception as exc:
                core.logger.exception("[CLEANUP] cleanup_call error for %s: %s", call_id, exc)
    except Exception:
        pass

    print(
        f"[DEBUG_PRINT] on_call_start called call_id={call_id} client_id={effective_client_id} "
        f"self.client_id={core.client_id}",
        flush=True,
    )

    if call_id in core._call_started_calls:
        print(
            f"[DEBUG_PRINT] on_call_start=skipped call_id={call_id} reason=already_called",
            flush=True,
        )
        core.logger.info(
            "[AICORE] on_call_start=skipped call_id=%s reason=already_called",
            call_id,
        )
        return

    print(
        f"[DEBUG_PRINT] on_call_start proceeding call_id={call_id} "
        f"effective_client_id={effective_client_id}",
        flush=True,
    )
    core.logger.info(
        "[AICORE] on_call_start() call_id=%s client_id=%s",
        call_id,
        effective_client_id,
    )
    core._call_started_calls.add(call_id)

    state = get_session_state(core, call_id)
    if not hasattr(state, "meta") or state.meta is None:
        state.meta = {}
    state.meta["client_id"] = effective_client_id

    if effective_client_id == "001":
        print("[DEBUG_PRINT] client_id=001 detected, proceeding with intro template", flush=True)
        state = get_session_state(core, call_id)
        state.phase = "INTRO"
        core.logger.debug(
            "[AICORE] Phase set to INTRO for call_id=%s (client_id=001, will change to ENTRY after intro)",
            call_id,
        )
        if hasattr(core, "tts_callback") and core.tts_callback:
            print("[DEBUG_PRINT] tts_callback is set, calling with template 000-002", flush=True)
            try:
                print(
                    f"[DEBUG_PRINT] intro=queued template_id=000-002 call_id={call_id}",
                    flush=True,
                )
                core.logger.info(
                    "[AICORE] intro=queued template_id=000-002 call_id=%s",
                    call_id,
                )
                try:
                    try:
                        core.current_system_text = core._render_templates(["000-002"]) or ""
                    except Exception:
                        core.current_system_text = "000-002"
                except Exception:
                    pass
                core.tts_callback(call_id, None, ["000-002"], False)  # type: ignore[misc, attr-defined]
                core._intro_played_calls.add(call_id)
                print(
                    f"[DEBUG_PRINT] intro=sent template_id=000-002 call_id={call_id}",
                    flush=True,
                )
                core.logger.info(
                    "[AICORE] intro=sent template_id=000-002 call_id=%s",
                    call_id,
                )

                state = get_session_state(core, call_id)
                state.phase = "ENTRY"
                core.logger.debug(
                    "[AICORE] Phase changed from INTRO to ENTRY for call_id=%s (after intro sent)",
                    call_id,
                )

                core.logger.debug(
                    "[AICORE] intro_sent entry_templates=deferred (will be sent by on_transcript when user speaks) "
                    "call_id=%s",
                    call_id,
                )

            except Exception as exc:
                core.logger.exception(
                    "[AICORE] intro=error template_id=000-002 call_id=%s error=%s",
                    call_id,
                    exc,
                )
                state = get_session_state(core, call_id)
                state.phase = "ENTRY"
        else:
            print(f"[DEBUG_PRINT] intro=error tts_callback not set call_id={call_id}", flush=True)
            core.logger.warning(
                "[AICORE] intro=error tts_callback not set, cannot send template 000-002"
            )
            state = get_session_state(core, call_id)
            state.phase = "ENTRY"
    else:
        state = get_session_state(core, call_id)
        state.phase = "ENTRY"
        core.logger.debug(
            "[AICORE] Phase set to ENTRY for call_id=%s (client_id=%s)",
            call_id,
            effective_client_id,
        )


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
