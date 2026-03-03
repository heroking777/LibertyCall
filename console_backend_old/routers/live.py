"""ライブ通話APIルーター（SSE + REST）."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
from jose import jwt

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from ..database import get_db
from ..models import Call, CallLog, User
from ..config import get_settings
from ..auth import get_current_user

router = APIRouter(prefix="/live", tags=["live"])
settings = get_settings()
logger = logging.getLogger(__name__)

# インメモリのイベントキュー（call_id -> list of asyncio.Queue）
_subscribers: dict[str, list[asyncio.Queue]] = {}


def publish_event(call_id: str, event_type: str, data: dict) -> None:
    """イベントを全サブスクライバーに配信."""
    logger.info(f"[SSE] publish_event call_id={call_id} event={event_type} subs={len(_subscribers.get(call_id, []))}")
    queues = _subscribers.get(call_id, [])
    dead = []
    for q in queues:
        try:
            q.put_nowait({"event": event_type, "data": data})
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        queues.remove(q)




@router.post("/calls/{call_id}/push_event")
async def push_event(
    call_id: str,
    request: dict,
    db: Session = Depends(get_db),
):
    """ws_sinkから呼ばれるイベント配信用エンドポイント."""
    # 簡易認証（内部通信のみ）
    event_type = request.get("event", "new_log")
    data = request.get("data", {})
    logger.info(f"[SSE] push_event received call_id={call_id} event={event_type} subs={len(_subscribers.get(call_id, []))}")
    publish_event(call_id, event_type, data)
    return {"ok": True}

@router.get("/active")
def get_active_calls(
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """アクティブ通話一覧を取得."""
    stmt = select(Call).where(Call.ended_at.is_(None))
    if current_user.role == "client_admin":
        stmt = stmt.where(Call.client_id == current_user.client_id)
    elif client_id:
        stmt = stmt.where(Call.client_id == client_id)
    stmt = stmt.order_by(Call.started_at.desc())
    calls = db.scalars(stmt).all()
    return {
        "calls": [
            {
                "call_id": c.call_id,
                "client_id": c.client_id,
                "caller_number": c.caller_number,
                "started_at": c.started_at.isoformat() + "Z" if c.started_at else None,
                "current_state": c.current_state,
                "is_transferred": c.is_transferred,
                "handover_summary": c.handover_summary,
            }
            for c in calls
        ]
    }


@router.get("/calls/{call_id}")
def get_call_detail(
    call_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通話詳細 + 全ログを取得."""
    call = db.scalar(select(Call).where(Call.call_id == call_id))
    if not call:
        raise HTTPException(status_code=404, detail="通話が見つかりません")
    if current_user.role == "client_admin" and call.client_id != current_user.client_id:
        raise HTTPException(status_code=403, detail="アクセス権限がありません")
    logs = db.scalars(
        select(CallLog).where(CallLog.call_id == call_id).order_by(CallLog.timestamp)
    ).all()
    return {
        "call": {
            "call_id": call.call_id,
            "client_id": call.client_id,
            "caller_number": call.caller_number,
            "started_at": call.started_at.isoformat() + "Z" if call.started_at else None,
            "ended_at": call.ended_at.isoformat() + "Z" if call.ended_at else None,
            "current_state": call.current_state,
            "is_transferred": call.is_transferred,
            "handover_summary": call.handover_summary,
        },
        "logs": [
            {
                "id": log.id,
                "role": log.role,
                "text": log.text,
                "state": log.state,
                "timestamp": log.timestamp.isoformat() + "Z" if log.timestamp else None,
            }
            for log in logs
        ],
    }


@router.get("/calls/{call_id}/stream")
async def stream_call_logs(
    call_id: str,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """SSEで通話ログをリアルタイム配信（EventSource用にクエリパラメータ認証対応）."""
    if not token:
        raise HTTPException(status_code=401, detail="認証が必要です")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", 0))
    except Exception:
        raise HTTPException(status_code=401, detail="無効なトークン")
    current_user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="ユーザーが見つかりません")
    call = db.scalar(select(Call).where(Call.call_id == call_id))
    if not call:
        raise HTTPException(status_code=404, detail="通話が見つかりません")
    if current_user.role == "client_admin" and call.client_id != current_user.client_id:
        raise HTTPException(status_code=403, detail="アクセス権限がありません")

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    if call_id not in _subscribers:
        _subscribers[call_id] = []
    _subscribers[call_id].append(queue)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'event': 'connected', 'data': {'call_id': call_id}})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if call_id in _subscribers:
                try:
                    _subscribers[call_id].remove(queue)
                except ValueError:
                    pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
