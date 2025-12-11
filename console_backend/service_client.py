"""サービスクライアント - 同期的なDB操作を提供."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .database import SessionLocal
from .services.call_service import (
    ensure_call,
    append_log,
    mark_transfer as mark_transfer_service,
    complete_call as complete_call_service,
)
from .schemas import AppendLogRequest


def start_call(
    call_id: str,
    client_id: str,
    *,
    started_at: Optional[datetime] = None,
    state: str = "init",
    caller_number: Optional[str] = None,
) -> None:
    """通話を開始."""
    with SessionLocal() as db:
        ensure_call(
            db,
            call_id=call_id,
            client_id=client_id,
            started_at=started_at,
            state=state,
            caller_number=caller_number,
        )


def append_call_log(
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
    """通話ログを追加."""
    with SessionLocal() as db:
        request = AppendLogRequest(
            role=role,
            text=text,
            state=state,
            timestamp=timestamp,
            caller_number=caller_number,
            template_id=template_id,
        )
        append_log(db, call_id=call_id, request=request, client_id=client_id)


def mark_transfer(call_id: str, summary: str) -> None:
    """転送をマーク."""
    with SessionLocal() as db:
        mark_transfer_service(db, call_id=call_id, summary=summary)


def complete_call(call_id: str, *, ended_at: Optional[datetime] = None) -> None:
    """通話を完了."""
    with SessionLocal() as db:
        complete_call_service(db, call_id=call_id, ended_at=ended_at)


def send_audio_level(
    call_id: str,
    level: float,
    *,
    direction: str = "user",
    client_id: Optional[str] = None,
) -> None:
    """音声レベルを送信（WebSocket経由）."""
    # WebSocket経由で送信する実装が必要な場合は、ここに追加
    # 現時点ではDBには保存しない
    pass

