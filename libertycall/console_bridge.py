"""管理コンソールとの連携を抽象化するブリッジ."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

try:
    from console_backend import service_client as _service_client
except Exception as exc:  # pragma: no cover - 例外時のみ
    _service_client = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "on", "yes"}


class ConsoleBridge:
    """service_client を安全に呼び出すためのラッパー。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.api_base_url = os.getenv("LIBERTYCALL_CONSOLE_API_BASE_URL", "http://localhost:8000")
        enabled_flag = _env_bool("LIBERTYCALL_CONSOLE_ENABLED", False)
        if not enabled_flag:
            self.enabled = False
            self.logger.info("LibertyCall console bridge is disabled via env flag.")
        elif _service_client is None:
            self.enabled = False
            self.logger.warning(
                "LibertyCall console bridge requested but console_backend import failed: %s",
                _IMPORT_ERROR,
            )
        else:
            self.enabled = True
            self.logger.info(
                "LibertyCall console bridge enabled (API base: %s)",
                self.api_base_url,
            )

    # ------------------------------------------------------------------ helpers
    def issue_call_id(self, client_id: Optional[str]) -> str:
        """通話IDを生成（in-YYYYMMDDHHMMSS形式）."""
        from datetime import datetime
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d%H%M%S")
        # マイクロ秒の下2桁を追加して重複を避ける
        microsecond_suffix = str(now.microsecond)[-2:]
        return f"in-{timestamp}{microsecond_suffix}"

    def _safe_call(self, func_name: str, *args, **kwargs) -> None:
        if not self.enabled or _service_client is None:
            return
        func = getattr(_service_client, func_name)
        try:
            func(*args, **kwargs)
        except Exception:  # pragma: no cover - ロガーだけの分岐
            self.logger.exception("Console bridge call failed: %s", func_name)

    # ----------------------------------------------------------------- facade
    def start_call(
        self,
        call_id: str,
        client_id: str,
        *,
        state: str = "init",
        started_at: Optional[datetime] = None,
        caller_number: Optional[str] = None,
    ) -> None:
        self._safe_call(
            "start_call",
            call_id=call_id,
            client_id=client_id,
            started_at=started_at,
            state=state,
            caller_number=caller_number,
        )

    def append_log(
        self,
        call_id: str,
        *,
        role: str,
        text: str,
        state: str,
        timestamp: Optional[datetime] = None,
        client_id: Optional[str] = None,
        caller_number: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> None:
        self._safe_call(
            "append_call_log",
            call_id=call_id,
            role=role,
            text=text,
            state=state,
            timestamp=timestamp,
            client_id=client_id,
            caller_number=caller_number,
            template_id=template_id,
        )

    def mark_transfer(self, call_id: str, summary: str) -> None:
        self._safe_call("mark_transfer", call_id, summary)

    def complete_call(self, call_id: str, *, ended_at: Optional[datetime] = None) -> None:
        self._safe_call("complete_call", call_id, ended_at=ended_at)

    def record_event(self, call_id: str, event_type: str, payload: dict) -> None:
        """
        個別イベントを履歴DBに記録する（例: 無音検出による自動切断）
        """
        try:
            record = {
                "call_id": call_id,
                "event_type": event_type,
                "payload": payload,
                "created_at": datetime.utcnow(),
            }

            # DBまたはファイルに記録
            if hasattr(self, "db") and self.db:
                self.db["call_events"].insert_one(record)
            else:
                event_log = Path("/opt/libertycall/logs/call_events.log")
                event_log.parent.mkdir(parents=True, exist_ok=True)
                with event_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

            self.logger.info(f"[CALL_EVENT] {event_type} recorded for {call_id}")

        except Exception as e:
            self.logger.error(
                f"[CALL_EVENT_ERROR] failed to record {event_type} for {call_id}: {e}",
                exc_info=True,
            )

    def send_audio_level(
        self,
        call_id: str,
        level: float,
        *,
        direction: str = "user",
        client_id: Optional[str] = None,
    ) -> None:
        """音声レベルを管理画面に送信（軽量、例外吸収あり）。"""
        self._safe_call(
            "send_audio_level",
            call_id=call_id,
            level=level,
            direction=direction,
            client_id=client_id,
        )


console_bridge = ConsoleBridge()

