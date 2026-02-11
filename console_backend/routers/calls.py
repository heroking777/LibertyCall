"""通話履歴APIルーター."""

import json
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Set
from fastapi import APIRouter, HTTPException, Query, Depends, Request, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.call_service import list_calls
from ..models import Call, User
from ..auth import get_current_user as auth_get_current_user

# MongoDBはオプショナル（インストールされていない場合もある）
try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    MongoClient = None
    ConnectionFailure = None

router = APIRouter(prefix="/calls", tags=["calls"])

# ファイルベースのログパス
CALL_EVENTS_LOG_PATH = Path("/opt/libertycall/logs/call_events.log")


def check_call_access(current_user: User, client_id: str) -> bool:
    if current_user.role == "super_admin":
        return True
    if current_user.role == "client_admin" and current_user.client_id == client_id:
        return True
    return False

# SSE購読者管理（リアルタイム更新用）
sse_subscribers: Set[asyncio.Queue] = set()


def get_mongo_client():
    """MongoDBクライアントを取得（オプション）."""
    if not MONGO_AVAILABLE:
        return None
    
    try:
        # MongoDB接続設定（環境変数から取得、デフォルトはlocalhost）
        mongo_url = "mongodb://localhost:27017/"
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=2000)
        # 接続確認
        client.admin.command('ping')
        return client
    except (ConnectionFailure, Exception):
        # MongoDBが利用できない場合はNoneを返す
        return None


def load_events_from_file() -> Dict[str, Dict[str, Any]]:
    """ファイルベースのログからイベントを読み込む."""
    events = {}
    if not CALL_EVENTS_LOG_PATH.exists():
        return events
    
    try:
        with open(CALL_EVENTS_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    call_id = event.get("call_id")
                    if call_id:
                        # 最新のイベントを保持（同じcall_idが複数ある場合は上書き）
                        events[call_id] = {
                            "event_type": event.get("event_type"),
                            "event_payload": event.get("payload", {}),
                        }
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to read call events from file: {e}")
    
    return events


@router.get("/history")
def get_calls_history(
    client_id: Optional[str] = Query(None, description="クライアントID"),
    limit: int = Query(100, ge=1, le=1000, description="取得件数"),
    offset: int = Query(0, ge=0, description="オフセット"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth_get_current_user),
):
    """
    通話履歴を取得（event_type / payload を含む）.
    
    MongoDBのcall_eventsコレクションから最新のイベントをJOINして返す。
    """
    # 権限チェック
    if not client_id:
        if current_user.role == "client_admin":
            client_id = current_user.client_id
        else:
            raise HTTPException(status_code=400, detail="client_idが必要です")
    
    if not check_call_access(current_user, client_id):
        raise HTTPException(status_code=403, detail="アクセス権限がありません")
    
    # 通話一覧を取得
    calls, total = list_calls(
        db,
        client_id=client_id,
        active=False,  # 終了した通話のみ
        limit=limit,
        offset=offset,
    )
    
    # イベントデータを取得（MongoDB優先、フォールバックはファイル）
    call_events = {}
    call_ids = [call.call_id for call in calls]
    
    if call_ids:
        # MongoDBから取得を試みる
        mongo_client = get_mongo_client()
        if mongo_client:
            try:
                db_mongo = mongo_client.get_database("libertycall")
                events_collection = db_mongo.get_collection("call_events")
                
                # 各call_idごとに最新のイベントを取得（created_at降順）
                for call_id in call_ids:
                    event = events_collection.find_one(
                        {"call_id": call_id},
                        sort=[("created_at", -1)]  # 降順
                    )
                    if event:
                        call_events[call_id] = {
                            "event_type": event.get("event_type"),
                            "event_payload": event.get("payload", {}),
                        }
            except Exception as e:
                # MongoDBエラーは無視（ログに記録のみ）
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to fetch call events from MongoDB: {e}")
            finally:
                mongo_client.close()
        
        # MongoDBが利用できない、または一部のcall_idでイベントが見つからない場合はファイルから読み込む
        file_events = load_events_from_file()
        for call_id in call_ids:
            if call_id not in call_events and call_id in file_events:
                call_events[call_id] = file_events[call_id]
    
    # レスポンスを構築
    result = []
    for call in calls:
        event_data = call_events.get(call.call_id, {})
        result.append({
            "call_id": call.call_id,
            "caller": call.caller_number or "unknown",
            "started_at": call.started_at.isoformat() if call.started_at else None,
            "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            "event_type": event_data.get("event_type"),
            "event_payload": event_data.get("event_payload"),
        })
    
    return {
        "calls": result,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/record_event")
async def record_event(request: Request):
    """
    Gatewayからの通話イベント（例: auto_hangup_silence）を受信し、DBまたはログに記録
    """
    try:
        body = await request.json()
        record = {
            "call_id": body.get("call_id"),
            "event_type": body.get("event_type"),
            "payload": body.get("payload"),
            "received_at": datetime.utcnow().isoformat(),
        }
        
        # MongoDBまたはファイルに保存
        try:
            mongo_client = get_mongo_client()
            if mongo_client:
                db_mongo = mongo_client.get_database("libertycall")
                events_collection = db_mongo.get_collection("call_events")
                events_collection.insert_one(record)
                mongo_client.close()
            else:
                # MongoDBが利用できない場合はファイルに保存
                log_path = Path("/opt/libertycall/logs/call_events.log")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as db_err:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[record_event] DB write failed: {db_err}", exc_info=True)
        
        return {"status": "ok", "record": record}
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[record_event] Failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.post("/push_event")
async def push_event(request: Request):
    """
    Gatewayからのリアルタイムイベントを受信し、SSE購読者に配信する.
    
    リクエストボディ:
    {
        "call_id": "通話ID",
        "summary": "要約テキスト（オプション）",
        "event": {
            "timestamp": "ISO形式のタイムスタンプ",
            "role": "AI" or "USER",
            "text": "発話テキスト"
        }
    }
    """
    try:
        body = await request.json()
        call_id = body.get("call_id")
        
        if not call_id:
            return {"status": "error", "error": "call_id is required"}
        
        # push_call_event()を呼び出してSSE購読者に配信
        summary = body.get("summary")
        event = body.get("event")
        
        await push_call_event(call_id, summary=summary, event=event)
        
        return {"status": "ok", "call_id": call_id}
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[push_event] Failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


async def push_call_event(call_id: str, summary: Optional[str] = None, event: Optional[Dict[str, Any]] = None):
    """
    通話イベントをSSE購読者にプッシュする（リアルタイム更新用）.
    
    Args:
        call_id: 通話ID
        summary: 要約テキスト（更新時）
        event: イベントデータ（会話ログなど）
    """
    if not sse_subscribers:
        return
    
    data = {
        "call_id": call_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if summary:
        data["summary"] = summary
    if event:
        data["event"] = event
    
    # すべての購読者にイベントを送信
    for queue in list(sse_subscribers):
        try:
            await queue.put(data)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to push event to subscriber: {e}")


@router.get("/stream")
async def calls_stream(request: Request, id: Optional[str] = Query(None, description="通話ID（フィルタ用）")):
    """
    SSEストリームエンドポイント（リアルタイム更新用）.
    
    通話中の会話ログや要約更新をリアルタイムで配信します。
    """
    async def event_generator():
        queue = asyncio.Queue()
        sse_subscribers.add(queue)
        
        try:
            # 接続確認のための初期メッセージ
            yield f"data: {json.dumps({'type': 'connected', 'call_id': id})}\n\n"
            
            while True:
                # クライアントが切断したかチェック
                if await request.is_disconnected():
                    break
                
                try:
                    # キューからイベントを取得（タイムアウト付き）
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    
                    # call_idフィルタリング
                    if id and event.get("call_id") != id:
                        continue
                    
                    # SSE形式で送信
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # タイムアウト時はハートビートを送信（接続維持）
                    yield f": heartbeat\n\n"
                    continue
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error in event stream: {e}", exc_info=True)
                    break
        finally:
            sse_subscribers.discard(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginxバッファリング無効化
        }
    )

