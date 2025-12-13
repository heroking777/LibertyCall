"""通話履歴APIルーター."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.call_service import list_calls
from ..models import Call

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
):
    """
    通話履歴を取得（event_type / payload を含む）.
    
    MongoDBのcall_eventsコレクションから最新のイベントをJOINして返す。
    """
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

