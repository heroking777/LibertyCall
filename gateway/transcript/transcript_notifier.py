"""Notification helpers for transcript events."""
from __future__ import annotations

import logging
from typing import Optional

try:
    from scripts.send_webhook_notification import send_notification
except Exception:  # pragma: no cover - optional dependency
    send_notification = None


def notify_event(
    logger: logging.Logger,
    event_type: str,
    message: str,
    call_id: Optional[str] = None,
) -> None:
    if not send_notification:
        logger.debug("[TRANSCRIPT_NOTIFY] notifier unavailable")
        return

    try:
        send_notification(event_type, message, call_id=call_id)
    except Exception as exc:
        logger.debug("[TRANSCRIPT_NOTIFY] failed: %s", exc)
