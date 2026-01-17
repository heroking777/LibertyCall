"""Conversation/hand-off state helper classes extracted from ai_core."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .text_utils import interpret_handoff_reply


class ConversationState:
    """Thin wrapper around the raw session_state dict used by AICore."""

    def __init__(self, raw: Dict[str, Any]) -> None:
        self.raw = raw

    @property
    def phase(self) -> str:
        return self.raw.get("phase", "ENTRY")

    @phase.setter
    def phase(self, value: str) -> None:
        self.raw["phase"] = value

    @property
    def last_intent(self) -> Optional[str]:
        return self.raw.get("last_intent")

    @last_intent.setter
    def last_intent(self, value: Optional[str]) -> None:
        self.raw["last_intent"] = value

    @property
    def handoff_state(self) -> str:
        return self.raw.get("handoff_state", "idle")

    @handoff_state.setter
    def handoff_state(self, value: str) -> None:
        self.raw["handoff_state"] = value

    @property
    def handoff_retry_count(self) -> int:
        return int(self.raw.get("handoff_retry_count", 0))

    @handoff_retry_count.setter
    def handoff_retry_count(self, value: int) -> None:
        self.raw["handoff_retry_count"] = int(value)

    @property
    def transfer_requested(self) -> bool:
        return bool(self.raw.get("transfer_requested", False))

    @transfer_requested.setter
    def transfer_requested(self, value: bool) -> None:
        self.raw["transfer_requested"] = bool(value)

    @property
    def transfer_executed(self) -> bool:
        return bool(self.raw.get("transfer_executed", False))

    @transfer_executed.setter
    def transfer_executed(self, value: bool) -> None:
        self.raw["transfer_executed"] = bool(value)

    @property
    def unclear_streak(self) -> int:
        return int(self.raw.get("unclear_streak", 0))

    @unclear_streak.setter
    def unclear_streak(self, value: int) -> None:
        self.raw["unclear_streak"] = int(value)

    @property
    def not_heard_streak(self) -> int:
        return int(self.raw.get("not_heard_streak", 0))

    @not_heard_streak.setter
    def not_heard_streak(self, value: int) -> None:
        self.raw["not_heard_streak"] = int(value)

    @property
    def handoff_completed(self) -> bool:
        return bool(self.raw.get("handoff_completed", False))

    @handoff_completed.setter
    def handoff_completed(self, value: bool) -> None:
        self.raw["handoff_completed"] = bool(value)

    @property
    def handoff_prompt_sent(self) -> bool:
        return bool(self.raw.get("handoff_prompt_sent", False))

    @handoff_prompt_sent.setter
    def handoff_prompt_sent(self, value: bool) -> None:
        self.raw["handoff_prompt_sent"] = bool(value)

    @property
    def meta(self) -> Dict[str, Any]:
        data = self.raw.get("meta")
        if not isinstance(data, dict):
            data = {}
            self.raw["meta"] = data
        return data

    @meta.setter
    def meta(self, value: Dict[str, Any]) -> None:
        self.raw["meta"] = value

    @property
    def last_ai_templates(self) -> List[str]:
        templates = self.raw.get("last_ai_templates")
        if not isinstance(templates, list):
            templates = []
            self.raw["last_ai_templates"] = templates
        return templates

    @last_ai_templates.setter
    def last_ai_templates(self, value: List[str]) -> None:
        self.raw["last_ai_templates"] = value

    @property
    def no_input_streak(self) -> int:
        return int(self.raw.get("no_input_streak", 0))

    @no_input_streak.setter
    def no_input_streak(self, value: int) -> None:
        self.raw["no_input_streak"] = int(value)


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
