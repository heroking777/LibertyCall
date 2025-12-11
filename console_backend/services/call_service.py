"""通話関連サービス."""

from __future__ import annotations

from datetime import datetime, date, UTC
from typing import Iterable, Optional, Literal
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..schemas import CallListResponse, CallDetailResponse, AppendLogRequest
from ..models import Call, CallLog
from ..websocket.dispatcher import call_event_dispatcher
from ..config import get_settings
from .file_log_service import append_log as append_file_log


def ensure_call(
    db: Session,
    call_id: str,
    client_id: str,
    *,
    started_at: Optional[datetime] = None,
    state: str = "init",
    caller_number: Optional[str] = None,
) -> Call:
    """通話を確保（存在しない場合は作成）."""
    import logging
    logger = logging.getLogger(__name__)
    
    # caller_numberをログで確認（DB保存前）
    logger.info(f"[ensure_call] call_id={call_id}, caller_number={caller_number}")
    
    call = db.scalar(select(Call).where(Call.call_id == call_id))
    if call is None:
        # 新規作成時はcaller_numberを必ず設定
        call = Call(
            call_id=call_id,
            client_id=client_id,
            started_at=started_at or datetime.now(UTC),
            current_state=state,
            caller_number=caller_number if caller_number and caller_number.strip() and caller_number != "-" else None,
        )
        db.add(call)
        db.commit()
        db.refresh(call)
        logger.info(f"[ensure_call] Created new call: call_id={call_id}, caller_number={call.caller_number}")
    else:
        if state:
            call.current_state = state
        # caller_numberが未設定の場合のみ更新（初回優先）
        # ただし、caller_numberが空文字列でない場合は更新する
        if caller_number and caller_number.strip() and caller_number != "-":
            if not call.caller_number or call.caller_number == "-":
                call.caller_number = caller_number
                logger.info(f"[ensure_call] Updated caller_number: call_id={call_id}, caller_number={call.caller_number}")
        db.commit()
    return call


def append_log(
    db: Session,
    call_id: str,
    request: AppendLogRequest,
    client_id: Optional[str] = None,
) -> CallLog:
    """ログを追加."""
    call = ensure_call(
        db,
        call_id=call_id,
        client_id=client_id or "",
        state=request.state,
        caller_number=request.caller_number,
    )
    
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
    
    # ファイルログに追記（例外は握りつぶす）
    try:
        settings = get_settings()
        append_file_log(call, log, settings, template_id=request.template_id)
    except Exception:
        # ファイル書き込みエラーは通話処理を止めない
        pass
    
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

