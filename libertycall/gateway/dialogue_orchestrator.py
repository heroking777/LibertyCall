"""Conversation flow orchestrator for dialogue handling."""
from __future__ import annotations

from typing import List, Tuple

from .state_store import get_session_state
from .text_utils import normalize_text
from .dialogue_phases import (
    handle_entry_phase,
    handle_entry_confirm_phase,
    handle_waiting_phase,
    handle_not_heard_phase,
    handle_qa_phase,
    handle_after_085_phase,
    handle_closing_phase,
)
from .dialogue_handoff import handle_handoff_phase


def run_conversation_flow(core, call_id: str, raw_text: str) -> Tuple[List[str], str, bool]:
    state = get_session_state(core, call_id)
    normalized = normalize_text(raw_text)
    phase = state.phase
    intent = "UNKNOWN"
    template_ids: List[str] = []
    transfer_requested = False

    if phase == "END":
        return [], "END_CALL", False
    if phase == "INTRO":
        core.logger.debug(
            "[AICORE] Phase=INTRO, skipping response (intro playing) call_id=%s",
            call_id,
        )
        return [], "UNKNOWN", False
    if phase == "ENTRY":
        intent, template_ids, transfer_requested = handle_entry_phase(
            core, call_id, raw_text, normalized, state
        )
    elif phase == "ENTRY_CONFIRM":
        intent, template_ids, transfer_requested = handle_entry_confirm_phase(
            core, call_id, raw_text, normalized, state
        )
    elif phase == "WAITING":
        intent, template_ids, transfer_requested = handle_waiting_phase(
            core, call_id, raw_text, normalized, state
        )
    elif phase == "NOT_HEARD":
        intent, template_ids, transfer_requested = handle_not_heard_phase(
            core, call_id, raw_text, normalized, state
        )
    elif phase == "QA":
        intent, template_ids, transfer_requested = handle_qa_phase(
            core, call_id, raw_text, state
        )
    elif phase == "AFTER_085":
        intent, template_ids, transfer_requested = handle_after_085_phase(
            core, call_id, raw_text, normalized, state
        )
    elif phase == "CLOSING":
        intent, template_ids, transfer_requested = handle_closing_phase(
            core, call_id, raw_text, normalized, state
        )
    elif phase in ("HANDOFF", "HANDOFF_CONFIRM_WAIT"):
        intent, template_ids, transfer_requested = handle_handoff_phase(
            core, call_id, raw_text, normalized, state
        )
    else:
        state.phase = "QA"
        intent, template_ids, transfer_requested = handle_qa_phase(
            core, call_id, raw_text, state
        )

    if not template_ids and state.phase != "END":
        intent = intent or "UNKNOWN"
        template_ids = ["110"]

    state.last_ai_templates = template_ids

    return template_ids, intent, transfer_requested
