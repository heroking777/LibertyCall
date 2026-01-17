"""State validation helpers for conversation state."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


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
