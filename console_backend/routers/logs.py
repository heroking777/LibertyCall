"""ログAPIルーター."""

from pathlib import Path
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import CallLogListResponse, CallLogDetailResponse, CallSummary, CallLogEntry
from ..services.log_reader_service import LogReaderService

router = APIRouter(prefix="/logs", tags=["logs"])

# ログベースディレクトリ（設定から取得）
from ..config import get_settings
settings = get_settings()
LOGS_BASE_DIR = settings.logs_base_dir

# ログリーダーサービスのシングルトンインスタンス
_log_reader_service: Optional[LogReaderService] = None


def get_log_reader_service() -> LogReaderService:
    """ログリーダーサービスを取得."""
    global _log_reader_service
    if _log_reader_service is None:
        _log_reader_service = LogReaderService(LOGS_BASE_DIR)
    return _log_reader_service


# TODO: 認証・権限チェックの依存関数を実装
# 現在は認証なしで動作（後で統合予定）
def get_current_user():
    """現在のユーザーを取得（認証用）."""
    # 仮実装：常にadminとして扱う
    return {"role": "admin", "client_id": None}


def check_access(user: dict, client_id: str) -> bool:
    """
    アクセス権限をチェック.
    
    Args:
        user: ユーザー情報（role, client_id）
        client_id: アクセスしようとしているクライアントID
        
    Returns:
        アクセス可能な場合True
    """
    user_role = user.get("role")
    user_client_id = user.get("client_id")
    
    # adminは全クライアントにアクセス可能
    if user_role == "admin":
        return True
    
    # clientは自分のクライアントIDのみアクセス可能
    if user_role == "client" and user_client_id == client_id:
        return True
    
    return False


@router.get("", response_model=CallLogListResponse)
def list_call_logs(
    client_id: str = Query(..., description="クライアントID"),
    date: Optional[str] = Query(None, description="日付（YYYY-MM-DD形式、デフォルトは今日）"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    通話ログ一覧を取得.
    
    Args:
        client_id: クライアントID
        date: 日付（YYYY-MM-DD形式、デフォルトは今日）
        db: データベースセッション
        current_user: 現在のユーザー
        
    Returns:
        通話ログ一覧
    """
    # アクセス権限チェック
    if not check_access(current_user, client_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 日付をパース
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        target_date = datetime.now()
    
    # ログリーダーサービスを使用して一覧を取得
    log_reader = get_log_reader_service()
    calls = log_reader.list_calls_for_date(client_id, target_date)
    
    # スキーマに変換
    call_summaries = [
        CallSummary(
            call_id=call["call_id"],
            started_at=call["started_at"],
            caller_number=call["caller_number"],
            summary=call["summary"],
        )
        for call in calls
    ]
    
    return CallLogListResponse(calls=call_summaries)


@router.get("/{client_id}/{call_id}", response_model=CallLogDetailResponse)
def get_call_log_detail(
    client_id: str,
    call_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    通話ログ詳細を取得.
    
    Args:
        client_id: クライアントID
        call_id: 通話ID
        db: データベースセッション
        current_user: 現在のユーザー
        
    Returns:
        通話ログ詳細
    """
    # アクセス権限チェック
    if not check_access(current_user, client_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # ログリーダーサービスを使用してログを取得
    log_reader = get_log_reader_service()
    call_data = log_reader.read_call_log(client_id, call_id)
    
    if not call_data["logs"]:
        raise HTTPException(status_code=404, detail="Call log not found")
    
    # スキーマに変換
    log_entries = [
        CallLogEntry(
            timestamp=log["timestamp"],
            caller_number=log["caller_number"],  # 各行のcaller_number（通常は同じ）
            role=log["role"],
            template_id=log["template_id"],
            text=log["text"],
        )
        for log in call_data["logs"]
    ]
    
    return CallLogDetailResponse(
        call_id=call_id,
        client_id=client_id,
        caller_number=call_data["caller_number"],
        started_at=call_data["started_at"],
        logs=log_entries,
    )

