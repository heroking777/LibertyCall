"""Call status logging helpers."""
from __future__ import annotations

from typing import Optional


def log_call_end(
    logger,
    call_id: str,
    source: str,
    client_id: str,
    phase: str,
    was_started: bool,
    was_intro_played: bool,
) -> None:
    logger.info(
        "[AICORE] on_call_end() call_id=%s source=%s client_id=%s phase=%s "
        "_call_started_calls=%s _intro_played_calls=%s -> cleared",
        call_id,
        source,
        client_id,
        phase,
        was_started,
        was_intro_played,
    )


def log_duplicate_call_start(logger, call_id: str) -> None:
    try:
        logger.warning("[CALL_START] Ignored duplicate start event for %s", call_id)
    except Exception:
        pass


def log_call_start_proceeding(logger, call_id: str, client_id: str, core_client_id: str) -> None:
    logger.info(
        "[AICORE] on_call_start() call_id=%s client_id=%s",
        call_id,
        client_id,
    )


def log_call_start_entry(logger, call_id: str, client_id: Optional[str]) -> None:
    pass


def log_existing_active_session(logger, call_id: str) -> None:
    logger.warning(
        "[CLEANUP] Found existing active session for %s at start. Forcing cleanup.",
        call_id,
    )


def log_call_start_skipped(logger, call_id: str) -> None:
    logger.info(
        "[AICORE] on_call_start=skipped call_id=%s reason=already_called",
        call_id,
    )


def log_intro_phase_start(logger, call_id: str) -> None:
    logger.debug(
        "[AICORE] Phase set to INTRO for call_id=%s (client_id=001, will change to ENTRY after intro)",
        call_id,
    )


def log_intro_tts_callback_set() -> None:


def log_intro_queued(logger, call_id: str) -> None:
    logger.info(
        "[AICORE] intro=queued template_id=000-002 call_id=%s",
        call_id,
    )


def log_intro_sent(logger, call_id: str) -> None:
    logger.info(
        "[AICORE] intro=sent template_id=000-002 call_id=%s",
        call_id,
    )


def log_intro_error(logger, call_id: str, exc: Exception) -> None:
    logger.exception(
        "[AICORE] intro=error template_id=000-002 call_id=%s error=%s",
        call_id,
        exc,
    )


def log_intro_missing_tts(call_id: str, logger) -> None:
    logger.warning(
        "[AICORE] intro=error tts_callback not set, cannot send template 000-002"
    )


def log_phase_entry(logger, call_id: str, client_id: str) -> None:
    logger.debug(
        "[AICORE] Phase set to ENTRY for call_id=%s (client_id=%s)",
        call_id,
        client_id,
    )


def log_intro_phase_entry(logger, call_id: str) -> None:
    logger.debug(
        "[AICORE] Phase changed from INTRO to ENTRY for call_id=%s (after intro sent)",
        call_id,
    )
    logger.debug(
        "[AICORE] intro_sent entry_templates=deferred (will be sent by on_transcript when user speaks) "
        "call_id=%s",
        call_id,
    )
