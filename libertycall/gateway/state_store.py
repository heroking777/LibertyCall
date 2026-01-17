"""Session state store helpers extracted from AICore."""

from __future__ import annotations

from typing import Optional

from .state_logic import ConversationState


def get_session_state(core, call_id: str) -> ConversationState:
    key = call_id or "GLOBAL_CALL"
    if key not in core.session_states:
        client_id = core.call_client_map.get(call_id) or core.client_id or "000"
        core.session_states[key] = {
            "phase": "ENTRY",
            "last_intent": None,
            "handoff_state": "idle",
            "handoff_retry_count": 0,
            "transfer_requested": False,
            "transfer_executed": False,
            "handoff_prompt_sent": False,
            "not_heard_streak": 0,
            "unclear_streak": 0,
            "handoff_completed": False,
            "last_ai_templates": [],
            "meta": {"client_id": client_id},
        }
    return ConversationState(core.session_states[key])


def reset_session_state(core, call_id: Optional[str]) -> None:
    if not call_id:
        return
    core.session_states.pop(call_id, None)
    core.last_activity.pop(call_id, None)
