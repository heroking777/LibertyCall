"""Pydanticスキーマ定義."""

from datetime import datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict


class CallBase(BaseModel):
    """通話基本スキーマ."""
    
    call_id: str = Field(..., max_length=64)
    client_id: str = Field(..., max_length=128)
    caller_number: Optional[str] = None  # 発信者番号
    current_state: str = Field(default="init", max_length=64)
    is_transferred: bool = False
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    handover_summary: Optional[str] = None
    note: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class CallListResponse(CallBase):
    """通話一覧レスポンス."""
    
    model_config = ConfigDict(from_attributes=True)


class CallDetailResponse(CallBase):
    """通話詳細レスポンス."""
    
    model_config = ConfigDict(from_attributes=True)


class CallLogResponse(BaseModel):
    """通話ログレスポンス."""
    
    timestamp: datetime
    role: Literal["user", "ai"]
    text: str
    state: str
    
    model_config = ConfigDict(from_attributes=True)


class AppendLogRequest(BaseModel):
    """ログ追加リクエスト."""
    
    role: Literal["user", "ai"]
    text: str
    state: str
    timestamp: Optional[datetime] = None
    caller_number: Optional[str] = None  # 発信者番号
    template_id: Optional[str] = None  # テンプレートID（AIログ用）


# ログファイル読み取り用スキーマ
class CallLogEntry(BaseModel):
    """ログエントリ（ファイルから読み取った生ログ）."""
    
    timestamp: datetime
    caller_number: Optional[str] = None
    role: Literal["USER", "AI"]
    template_id: Optional[str] = None
    text: str


class CallLogDetailResponse(BaseModel):
    """通話ログ詳細レスポンス."""
    
    call_id: str
    client_id: str
    caller_number: Optional[str] = None
    started_at: Optional[datetime] = None
    logs: List[CallLogEntry]


class CallSummary(BaseModel):
    """通話要約（一覧用）."""
    
    call_id: str
    started_at: datetime
    caller_number: Optional[str] = None
    summary: str


class CallLogListResponse(BaseModel):
    """通話ログ一覧レスポンス."""
    
    calls: List[CallSummary]

