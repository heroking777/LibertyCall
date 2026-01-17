"""State update rules for conversation flow."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Tuple

from .state_validators import ConversationState
from .text_utils import interpret_handoff_reply

logger = logging.getLogger(__name__)


class MisunderstandingGuard:
    """Manages unclear/not-heard streaks and auto handoff triggers."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def check_auto_handoff_from_unclear(
        self,
        call_id: str,
        state: ConversationState,
        intent: str,
    ) -> Tuple[str, bool]:
        unclear_streak = state.unclear_streak
        handoff_state = state.handoff_state
        if (
            unclear_streak >= 2
            and handoff_state in ("idle", "done")
            and intent not in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO")
        ):
            state.meta["reason_for_handoff"] = "auto_unclear"
            state.meta["unclear_streak_at_trigger"] = unclear_streak
            self.logger.warning(
                "INTENT_FORCE_HANDOFF: call_id=%s unclear_streak=%d -> HANDOFF_REQUEST",
                call_id or "GLOBAL_CALL",
                unclear_streak,
            )
            return "HANDOFF_REQUEST", True
        return intent, False

    def handle_not_heard_streak(
        self,
        call_id: str,
        state: ConversationState,
        template_ids: List[str],
        intent: str,
        base_intent: str,
    ) -> Tuple[List[str], str, bool]:
        if template_ids == ["110"] and state.phase != "END":
            not_heard_streak = state.not_heard_streak + 1
            state.not_heard_streak = not_heard_streak
            if not_heard_streak >= 2:
                state.not_heard_streak = 0
                state.handoff_state = "confirming"
                state.handoff_prompt_sent = True
                state.transfer_requested = False
                updated_template_ids = ["0604"]
                self.logger.debug(
                    "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s",
                    call_id or "GLOBAL_CALL",
                    intent,
                    base_intent,
                    updated_template_ids,
                )
                return updated_template_ids, base_intent, True
        else:
            state.not_heard_streak = 0
        return template_ids, intent, False

    def handle_unclear_streak(
        self,
        call_id: str,
        state: ConversationState,
        template_ids: List[str],
    ) -> None:
        if template_ids == ["110"]:
            unclear_streak = state.unclear_streak + 1
            state.unclear_streak = unclear_streak
            self.logger.warning(
                "UNCLEAR_STREAK_INC: call_id=%s unclear_streak=%d tpl=110",
                call_id or "GLOBAL_CALL",
                unclear_streak,
            )
        else:
            normal_templates = {
                "006",
                "006_SYS",
                "010",
                "004",
                "005",
                "020",
                "021",
                "022",
                "023",
                "040",
                "041",
                "042",
                "060",
                "061",
                "070",
                "071",
                "072",
                "080",
                "081",
                "082",
                "084",
                "085",
                "086",
                "087",
                "088",
                "089",
                "090",
                "091",
                "092",
                "099",
                "100",
                "101",
                "102",
                "103",
                "104",
                "0600",
                "0601",
                "0602",
                "0603",
                "0604",
            }
            if any(tid in normal_templates for tid in template_ids):
                if state.unclear_streak > 0:
                    self.logger.warning(
                        "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=tpl_%s",
                        call_id or "GLOBAL_CALL",
                        template_ids[0] if template_ids else "unknown",
                    )
                state.unclear_streak = 0

    def reset_unclear_streak_on_handoff_done(
        self,
        call_id: str,
        state: ConversationState,
        reason: str = "handoff_done",
    ) -> None:
        if state.unclear_streak > 0:
            self.logger.warning(
                "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=%s",
                call_id or "GLOBAL_CALL",
                reason,
            )
        state.unclear_streak = 0


class HandoffStateMachine:
    """State machine that interprets HANDOFF confirmation replies."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def handle_confirm(
        self,
        call_id: str,
        raw_text: str,
        intent: str,
        state: Dict[str, Any],
        contains_no_keywords: Callable[[str], bool],
    ) -> Tuple[List[str], str, bool, Dict[str, Any]]:
        hand_intent = interpret_handoff_reply(raw_text)
        if hand_intent == "UNKNOWN":
            hand_intent = intent

        if hand_intent == "HANDOFF_YES":
            state["handoff_state"] = "done"
            state["handoff_retry_count"] = 0
            state["transfer_requested"] = True
            if state.get("unclear_streak", 0) > 0:
                self.logger.warning(
                    "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=handoff_done",
                    call_id or "GLOBAL_CALL",
                )
            state["unclear_streak"] = 0
            state["phase"] = "HANDOFF_DONE"
            state["handoff_completed"] = True
            template_ids = ["081", "082"]
            return template_ids, "HANDOFF_YES", True, state

        if hand_intent == "HANDOFF_NO":
            state["handoff_state"] = "done"
            state["handoff_retry_count"] = 0
            state["transfer_requested"] = False
            if state.get("unclear_streak", 0) > 0:
                self.logger.warning(
                    "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=handoff_done",
                    call_id or "GLOBAL_CALL",
                )
            state["unclear_streak"] = 0
            state["phase"] = "END"
            state["handoff_completed"] = True
            template_ids = ["086", "087"]
            return template_ids, "HANDOFF_NO", False, state

        retry = state.get("handoff_retry_count", 0)
        if retry == 0:
            state["handoff_state"] = "confirming"
            state["handoff_retry_count"] = 1
            state["transfer_requested"] = False
            template_ids = ["0604"]
            self.logger.debug(
                "[NLG_DEBUG] handoff_confirm_retry call_id=%s intent=%s retry=%s",
                call_id or "GLOBAL_CALL",
                hand_intent,
                retry,
            )
            return template_ids, "HANDOFF_FALLBACK_REASK", False, state

        self.logger.debug(
            "[NLG_DEBUG] handoff_confirm_ambiguous call_id=%s intent=%s retry=%s -> transfer",
            call_id or "GLOBAL_CALL",
            hand_intent,
            retry,
        )
        state["handoff_state"] = "done"
        state["handoff_retry_count"] = 0
        state["transfer_requested"] = True
        if state.get("unclear_streak", 0) > 0:
            self.logger.warning(
                "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=handoff_done",
                call_id or "GLOBAL_CALL",
            )
        state["unclear_streak"] = 0
        state["phase"] = "HANDOFF_DONE"
        state["handoff_completed"] = True
        template_ids = ["081", "082"]
        return template_ids, "HANDOFF_FALLBACK_YES", True, state
