"""Transcript persistence helpers."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from .state_store import get_session_state


def save_transcript_event(
    core,
    call_id: str,
    text: str,
    is_final: bool,
    kwargs: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    core.call_id = call_id
    core._save_transcript_event(call_id, text, is_final, kwargs)

    if call_id not in core.session_info:
        core.session_info[call_id] = {
            "start_time": datetime.now(),
            "intents": [],
            "phrases": [],
        }


def append_user_call_log(core, merged_text: str, logger: logging.Logger) -> None:
    try:
        core._append_call_log("USER", merged_text)
    except Exception as exc:
        logger.exception("CALL_LOGGING_ERROR (USER): %s", exc)


def reset_no_input_streak(
    core, call_id: str, merged_text: str, logger: logging.Logger
) -> None:
    if not merged_text:
        return
    state = get_session_state(core, call_id)
    if state.no_input_streak > 0:
        logger.info(
            "[NO_INPUT] call_id=%s streak reset (user input: %r)",
            call_id,
            merged_text[:20],
        )
        state.no_input_streak = 0
