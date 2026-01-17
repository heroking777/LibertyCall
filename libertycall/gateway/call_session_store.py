"""In-memory call session store helpers."""
from __future__ import annotations

from typing import Optional, Tuple

from .state_store import get_session_state


def get_call_metadata(core, call_id: str) -> Tuple[str, Optional[str]]:
    try:
        state = get_session_state(core, call_id)
        phase_at_end = state.phase
        client_id_from_state = (
            state.meta.get("client_id") if hasattr(state, "meta") and state.meta else None
        )
    except Exception:
        phase_at_end = "unknown"
        client_id_from_state = None
    return phase_at_end, client_id_from_state


def remove_call_tracking(core, call_id: str) -> Tuple[bool, bool]:
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

    return was_started, was_intro_played


def set_call_client_meta(core, call_id: str, client_id: str) -> None:
    state = get_session_state(core, call_id)
    if not hasattr(state, "meta") or state.meta is None:
        state.meta = {}
    state.meta["client_id"] = client_id


def mark_call_started(core, call_id: str) -> None:
    core._call_started_calls.add(call_id)


def mark_intro_played(core, call_id: str) -> None:
    core._intro_played_calls.add(call_id)
