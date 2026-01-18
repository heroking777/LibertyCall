"""Dialogue phase handlers extracted from dialogue_engine."""
from __future__ import annotations

from typing import List, Tuple

from ..common.text_utils import normalize_text, contains_keywords


def handle_entry_phase(
    core,
    call_id: str,
    raw_text: str,
    normalized_text: str,
    state,
) -> Tuple[str, List[str], bool]:
    if "ゴニョゴニョ" in raw_text or len(raw_text.strip()) == 0:
        state.phase = "QA"
        state.last_intent = "NOT_HEARD"
        template_ids = ["0602"]
        return "NOT_HEARD", template_ids, False
    if any(kw in raw_text.lower() for kw in ["もしもし", "こんにちは", "おはよう"]):
        state.phase = "QA"
        state.last_intent = "GREETING"
        return "GREETING", ["004"], False
    if contains_keywords(normalized_text, core.ENTRY_TRIGGER_KEYWORDS):
        state.phase = "ENTRY_CONFIRM"
        state.last_intent = "INQUIRY"
        return "INQUIRY", ["006"], False
    state.phase = "QA"
    return handle_qa_phase(core, call_id, raw_text, state)


def handle_qa_phase(core, call_id: str, raw_text: str, state) -> Tuple[str, List[str], bool]:
    intent = "UNKNOWN"
    handoff_state = state.handoff_state
    transfer_requested = state.transfer_requested

    if handoff_state == "done":
        template_ids = ["114"]
        template_ids = [tid for tid in template_ids if tid not in ("0604", "104")]
        if intent == "SALES_CALL":
            last_intent = state.last_intent
            if last_intent == "SALES_CALL":
                state.phase = "END"
            else:
                state.phase = "AFTER_085"
        elif intent == "END_CALL":
            state.phase = "END"
        else:
            state.phase = "AFTER_085"
        state.last_intent = intent
        return intent, template_ids, transfer_requested

    template_ids = ["114"]
    if intent == "SALES_CALL":
        last_intent = state.last_intent
        if last_intent == "SALES_CALL":
            state.phase = "END"
        else:
            state.phase = "AFTER_085"
    elif intent == "END_CALL":
        state.phase = "END"
    else:
        state.phase = "AFTER_085"
    state.last_intent = intent
    return intent, template_ids, transfer_requested


def handle_after_085_phase(
    core,
    call_id: str,
    raw_text: str,
    normalized_text: str,
    state,
) -> Tuple[str, List[str], bool]:
    intent = "UNKNOWN"
    handoff_keywords = ["担当者", "人間", "代わって", "つないで", "オペレーター"]
    if any(kw in raw_text for kw in handoff_keywords) and state.handoff_state in (
        "idle",
        "done",
    ):
        intent = "HANDOFF_REQUEST"
        state.handoff_state = "confirming"
        state.handoff_retry_count = 0
        state.handoff_prompt_sent = True
        state.transfer_requested = False
        state.transfer_executed = False
        template_ids = ["0604"]
        state.last_intent = intent
        return intent, template_ids, False

    if "営業" in raw_text:
        intent = "SALES_CALL"
        last_intent = state.last_intent
        if last_intent == "SALES_CALL":
            state.phase = "END"
            template_ids = ["094", "088"]
            if state.handoff_state == "done":
                template_ids = [tid for tid in template_ids if tid not in ["0604", "104"]]
            state.last_intent = intent
            return intent, template_ids, False

    if contains_keywords(normalized_text, core.AFTER_085_NEGATIVE_KEYWORDS):
        state.phase = "CLOSING"
        return "END_CALL", ["013"], False
    state.phase = "QA"
    return handle_qa_phase(core, call_id, raw_text, state)


def handle_entry_confirm_phase(
    core,
    call_id: str,
    raw_text: str,
    normalized_text: str,
    state,
) -> Tuple[str, List[str], bool]:
    if contains_keywords(normalized_text, core.CLOSING_YES_KEYWORDS):
        state.phase = "QA"
        state.last_intent = "INQUIRY"
        return "INQUIRY", ["010"], False
    if contains_keywords(normalized_text, core.CLOSING_NO_KEYWORDS):
        state.phase = "END"
        state.last_intent = "END_CALL"
        return "END_CALL", ["087", "088"], False
    state.phase = "QA"
    return handle_qa_phase(core, call_id, raw_text, state)


def handle_waiting_phase(
    core,
    call_id: str,
    raw_text: str,
    normalized_text: str,
    state,
) -> Tuple[str, List[str], bool]:
    if raw_text and len(raw_text.strip()) > 0:
        state.phase = "QA"
        return handle_qa_phase(core, call_id, raw_text, state)
    state.phase = "NOT_HEARD"
    return "NOT_HEARD", ["110"], False


def handle_not_heard_phase(
    core,
    call_id: str,
    raw_text: str,
    normalized_text: str,
    state,
) -> Tuple[str, List[str], bool]:
    state.phase = "QA"
    return handle_qa_phase(core, call_id, raw_text, state)


def handle_closing_phase(
    core,
    call_id: str,
    raw_text: str,
    normalized_text: str,
    state,
) -> Tuple[str, List[str], bool]:
    if contains_keywords(normalized_text, core.CLOSING_YES_KEYWORDS):
        state.phase = "HANDOFF"
        state.last_intent = "SETUP"
        return "SETUP", ["060", "061", "062", "104"], False
    if contains_keywords(normalized_text, core.CLOSING_NO_KEYWORDS):
        state.phase = "END"
        state.last_intent = "END_CALL"
        return "END_CALL", ["087", "088"], False
    state.phase = "QA"
    return handle_qa_phase(core, call_id, raw_text, state)
