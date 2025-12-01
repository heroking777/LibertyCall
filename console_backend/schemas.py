"""Pydanticスキーマ定義."""

from datetime import datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict


class CallBase(BaseModel):
    """通話基本スキーマ."""
    
    call_id: str = Field(..., max_length=64)
    client_id: str = Field(..., max_length=128)
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

