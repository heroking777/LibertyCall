"""データベースモデル定義."""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, UTC

from .database import Base


class Call(Base):
    """通話情報モデル."""
    
    __tablename__ = "calls"
    
    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String(64), unique=True, nullable=False, index=True)
    client_id = Column(String(128), nullable=False, index=True)
    caller_number = Column(String(32), nullable=True, index=True)  # 発信者番号
    started_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    ended_at = Column(DateTime, nullable=True)
    current_state = Column(String(64), default="init", nullable=False)
    is_transferred = Column(Boolean, default=False, nullable=False)
    handover_summary = Column(Text, nullable=True)
    
    # リレーション
    logs = relationship("CallLog", back_populates="call", cascade="all, delete-orphan")


class CallLog(Base):
    """通話ログモデル."""
    
    __tablename__ = "call_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String(64), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    role = Column(String(16), nullable=False)
    text = Column(Text, nullable=False)
    state = Column(String(64), nullable=False)
    
    # リレーション
    call = relationship("Call", back_populates="logs")

