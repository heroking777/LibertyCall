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
]

