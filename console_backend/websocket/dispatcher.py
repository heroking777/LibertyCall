"""WebSocketイベントディスパッチャー."""

from typing import Optional
from ..models import CallLog


class CallEventDispatcher:
    """通話イベントをWebSocket経由で送信."""
    
    def __init__(self):
        self._manager = None
    
    def set_manager(self, manager):
        """マネージャーを設定."""
        self._manager = manager
    
    def send_log(self, call_id: str, log: CallLog) -> None:
        """ログイベントを送信."""
        if self._manager:
            self._manager.broadcast_call_log(call_id, log)
    
    def send_call_update(self, call_id: str, data: dict) -> None:
        """通話更新イベントを送信."""
        if self._manager:
            self._manager.broadcast_call_update(call_id, data)


call_event_dispatcher = CallEventDispatcher()

