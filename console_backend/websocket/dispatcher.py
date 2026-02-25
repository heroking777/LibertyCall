"""WebSocket/SSEイベントディスパッチャー."""

import logging
from typing import Optional
from ..models import CallLog

logger = logging.getLogger(__name__)


class CallEventDispatcher:
    """通話イベントをSSE経由で送信."""

    def send_log(self, call_id: str, log: CallLog) -> None:
        try:
            from ..routers.live import publish_event
            publish_event(call_id, "new_log", {
                "id": log.id,
                "call_id": call_id,
                "role": log.role,
                "text": log.text,
                "state": log.state,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            })
        except Exception as e:
            logger.debug("SSE publish failed: %s", e)

    def send_call_update(self, call_id: str, data: dict) -> None:
        try:
            from ..routers.live import publish_event
            publish_event(call_id, "call_update", data)
        except Exception as e:
            logger.debug("SSE publish failed: %s", e)


call_event_dispatcher = CallEventDispatcher()
