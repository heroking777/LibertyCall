"""
対話フロー方式の応答判定ロジック

Intent方式の複雑さを排除し、自然な会話フローで誤案内ゼロを実現。
基本原則: 曖昧な質問には聞き返す。明確な質問には即答する。
"""

from .flow_transition_rules import (
    check_clear_price_question,
    check_clear_questions,
    contains_any,
    handle_function_type_response,
    handle_price_type_response,
    handle_setup_type_response,
    is_ambiguous_function_question,
    is_ambiguous_price_question,
    is_ambiguous_setup_question,
    is_end_call,
    is_greeting,
    is_handoff_request,
    is_not_heard,
    is_silence,
)
from .dialogue_orchestrator import run_conversation_flow

__all__ = [
    "check_clear_price_question",
    "check_clear_questions",
    "contains_any",
    "handle_function_type_response",
    "handle_price_type_response",
    "handle_setup_type_response",
    "is_ambiguous_function_question",
    "is_ambiguous_price_question",
    "is_ambiguous_setup_question",
    "is_end_call",
    "is_greeting",
    "is_handoff_request",
    "is_not_heard",
    "is_silence",
    "get_response",
]


def get_response(text: str, phase: str, state: dict | None = None):
    """Lightweight dialogue flow handler without core dependencies."""
    current_state = dict(state or {})
    text = text or ""

    if is_silence(text):
        silence_count = current_state.get("silence_count", 0)
        current_state["silence_count"] = silence_count + 1
        if silence_count >= 1:
            return ["0604"], "HANDOFF_CONFIRM_WAIT", current_state
        return ["110"], "QA", current_state

    if is_not_heard(text):
        return ["0602"], "QA", current_state

    if is_handoff_request(text):
        return ["0604"], "HANDOFF_CONFIRM_WAIT", current_state

    if is_end_call(text):
        return ["086"], "END", current_state

    clear_response = check_clear_questions(text)
    if clear_response:
        return clear_response, "QA", current_state

    if phase == "WAITING_PRICE_TYPE":
        return handle_price_type_response(text, current_state)
    if phase == "WAITING_FUNCTION_TYPE":
        return handle_function_type_response(text, current_state)
    if phase == "WAITING_SETUP_TYPE":
        return handle_setup_type_response(text, current_state)

    if is_ambiguous_price_question(text):
        current_state["waiting_retry_count"] = 0
        return ["115"], "WAITING_PRICE_TYPE", current_state
    if is_ambiguous_function_question(text):
        current_state["waiting_retry_count"] = 0
        return ["117"], "WAITING_FUNCTION_TYPE", current_state
    if is_ambiguous_setup_question(text):
        current_state["waiting_retry_count"] = 0
        return ["120"], "WAITING_SETUP_TYPE", current_state

    return ["114"], "QA", current_state

