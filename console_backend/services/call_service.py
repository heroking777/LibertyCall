"""通話関連サービス."""

from __future__ import annotations

from datetime import datetime, date, UTC
from typing import Iterable, Optional, Literal
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..schemas import CallListResponse, CallDetailResponse, AppendLogRequest
from ..models import Call, CallLog
from ..websocket.dispatcher import call_event_dispatcher


def ensure_call(
    db: Session,
    call_id: str,
    client_id: str,
    *,
    started_at: Optional[datetime] = None,
    state: str = "init",
) -> Call:
    """通話を確保（存在しない場合は作成）."""
    call = db.scalar(select(Call).where(Call.call_id == call_id))
    if call is None:
        call = Call(
            call_id=call_id,
            client_id=client_id,
            started_at=started_at or datetime.now(UTC),
            current_state=state,
        )
        db.add(call)
        db.commit()
        db.refresh(call)
    else:
        if state:
            call.current_state = state
        db.commit()
    return call


def append_log(
    db: Session,
    call_id: str,
    request: AppendLogRequest,
) -> CallLog:
    """ログを追加."""
    call = ensure_call(db, call_id=call_id, client_id="", state=request.state)
    
    log = CallLog(
        call_id=call_id,
        role=request.role,
        text=request.text,
        state=request.state,
        timestamp=request.timestamp or datetime.now(UTC),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    
    # WebSocketイベントを送信
    call_event_dispatcher.send_log(call_id, log)
    
    return log


def mark_transfer(db: Session, call_id: str, summary: str) -> Call:
    """転送をマーク."""
    call = db.scalar(select(Call).where(Call.call_id == call_id))
    if call:
        call.is_transferred = True
        call.handover_summary = summary
        db.commit()
        db.refresh(call)
    return call


def complete_call(
    db: Session,
    call_id: str,
    *,
    ended_at: Optional[datetime] = None,
) -> Call:
    """通話を完了."""
    call = db.scalar(select(Call).where(Call.call_id == call_id))
    if call:
        call.ended_at = ended_at or datetime.utcnow()
        db.commit()
        db.refresh(call)
    return call


def list_calls(
    db: Session,
    *,
    client_id: Optional[str] = None,
    active: Optional[bool] = None,
    only_transferred: Optional[bool] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Call], int]:
    """通話一覧を取得."""
    stmt = select(Call)
    count_stmt = select(func.count()).select_from(Call)
    
    conditions = []
    
    if client_id:
        conditions.append(Call.client_id == client_id)
    
    if active is not None:
        if active:
            conditions.append(Call.ended_at.is_(None))
        else:
            conditions.append(Call.ended_at.is_not(None))
    
    if only_transferred is not None:
        conditions.append(Call.is_transferred == only_transferred)
    
    if date_from:
        conditions.append(Call.started_at >= datetime.combine(date_from, datetime.min.time()))
    
    if date_to:
        conditions.append(Call.started_at <= datetime.combine(date_to, datetime.max.time()))
    
    if conditions:
        condition = and_(*conditions)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    
    total = db.scalar(count_stmt)
    
    calls = db.scalars(
        stmt.order_by(Call.started_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    
    return list(calls), total

