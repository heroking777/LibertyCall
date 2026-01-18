"""Handoff-specific dialogue handling."""
from __future__ import annotations

import os
from typing import List, Tuple

from ..common.text_utils import normalize_text, contains_keywords
from .prompt_factory import render_templates


def handle_handoff_confirm(core, call_id: str, raw_text: str, intent: str, state) -> Tuple[str, List[str], str, bool]:
    normalized = normalize_text(raw_text)

    def contains_no_keywords(text: str) -> bool:
        return contains_keywords(text, core.CLOSING_NO_KEYWORDS)

    template_ids, result_intent, transfer_requested, _ = core._handoff_sm.handle_confirm(
        call_id=call_id,
        raw_text=raw_text,
        intent=intent,
        state=state.raw,
        contains_no_keywords=lambda text=normalized: contains_no_keywords(text),
    )

    reply_text = render_templates(template_ids)

    if result_intent in ("HANDOFF_YES", "HANDOFF_FALLBACK_YES"):
        core._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)

    if result_intent == "HANDOFF_NO":
        key = call_id or "GLOBAL_CALL"
        if core.hangup_callback:
            core.logger.info(
                "AUTO_HANGUP_DIRECT_SCHEDULE: call_id=%s delay=60.0",
                key,
            )
            try:
                core._schedule_auto_hangup(key, delay_sec=60.0)
            except Exception as exc:
                core.logger.exception(
                    "AUTO_HANGUP_DIRECT_SCHEDULE_ERROR: call_id=%s error=%r",
                    key,
                    exc,
                )
        else:
            core.logger.warning(
                "AUTO_HANGUP_DIRECT_SKIP: call_id=%s reason=no_hangup_callback",
                key,
            )

    return reply_text, template_ids, result_intent, transfer_requested


def handle_handoff_phase(core, call_id: str, raw_text: str, normalized_text: str, state) -> Tuple[str, List[str], bool]:
    intent = "UNKNOWN"
    reply_text, template_ids, result_intent, transfer_requested = handle_handoff_confirm(
        core, call_id, raw_text, intent, state
    )

    if result_intent == "HANDOFF_YES":
        state.phase = "HANDOFF_DONE"
        state.last_intent = "HANDOFF_YES"
        state.handoff_completed = True
        state.transfer_requested = True
        core._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)
    elif result_intent == "HANDOFF_FALLBACK_YES":
        state.phase = "HANDOFF_DONE"
        state.last_intent = "HANDOFF_YES"
        state.handoff_completed = True
        state.transfer_requested = True
        core._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)
    elif result_intent in ("HANDOFF_NO", "HANDOFF_FALLBACK_NO"):
        state.phase = "END"
        state.last_intent = "END_CALL"
        state.handoff_completed = True
    else:
        state.phase = "HANDOFF_CONFIRM_WAIT"
        state.last_intent = "HANDOFF_REQUEST"

    return result_intent, template_ids, transfer_requested
