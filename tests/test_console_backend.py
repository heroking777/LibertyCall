"""console_backendモジュールのユニットテスト."""

import pytest
from datetime import datetime, UTC
from sqlalchemy.orm import Session

from console_backend.database import SessionLocal, Base, engine
from console_backend.models import Call, CallLog
from console_backend.service_client import (
    start_call,
    append_call_log,
    mark_transfer,
    complete_call,
)
from console_backend.services.call_service import (
    ensure_call,
    append_log,
    list_calls,
)
from console_backend.schemas import AppendLogRequest


@pytest.fixture(scope="function")
def db_session():
    """テスト用のデータベースセッション."""
    # テスト用にテーブルを作成
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        # テスト後にテーブルを削除
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_call_id():
    """テスト用のcall_id."""
    return f"test-{datetime.now(UTC).timestamp()}"


class TestServiceClient:
    """service_clientのテスト."""
    
    def test_start_call(self, db_session: Session, test_call_id: str):
        """start_callのテスト."""
        start_call(
            test_call_id,
            "test-client",
            started_at=datetime.now(UTC),
            state="init"
        )
        
        call = db_session.query(Call).filter(Call.call_id == test_call_id).first()
        assert call is not None
        assert call.call_id == test_call_id
        assert call.client_id == "test-client"
        assert call.current_state == "init"
        assert call.ended_at is None
    
    def test_append_call_log(self, db_session: Session, test_call_id: str):
        """append_call_logのテスト."""
        # まずcallを作成
        start_call(test_call_id, "test-client", state="init")
        
        # ログを追加
        append_call_log(
            test_call_id,
            role="user",
            text="テストメッセージ",
            state="greeting"
        )
        
        log = db_session.query(CallLog).filter(CallLog.call_id == test_call_id).first()
        assert log is not None
        assert log.role == "user"
        assert log.text == "テストメッセージ"
        assert log.state == "greeting"
    
    def test_complete_call(self, db_session: Session, test_call_id: str):
        """complete_callのテスト."""
        # まずcallを作成
        start_call(test_call_id, "test-client", state="init")
        
        # 完了
        complete_call(test_call_id, ended_at=datetime.now(UTC))
        
        call = db_session.query(Call).filter(Call.call_id == test_call_id).first()
        assert call is not None
        assert call.ended_at is not None
    
    def test_mark_transfer(self, db_session: Session, test_call_id: str):
        """mark_transferのテスト."""
        # まずcallを作成
        start_call(test_call_id, "test-client", state="init")
        
        # 転送をマーク
        mark_transfer(test_call_id, "転送サマリー")
        
        call = db_session.query(Call).filter(Call.call_id == test_call_id).first()
        assert call is not None
        assert call.is_transferred is True
        assert call.handover_summary == "転送サマリー"


class TestCallService:
    """call_serviceのテスト."""
    
    def test_ensure_call(self, db_session: Session, test_call_id: str):
        """ensure_callのテスト."""
        call = ensure_call(
            db_session,
            call_id=test_call_id,
            client_id="test-client",
            state="init"
        )
        
        assert call is not None
        assert call.call_id == test_call_id
        
        # 再度呼び出しても同じcallが返される
        call2 = ensure_call(
            db_session,
            call_id=test_call_id,
            client_id="test-client",
            state="updated"
        )
        
        assert call.id == call2.id
        assert call2.current_state == "updated"
    
    def test_append_log(self, db_session: Session, test_call_id: str):
        """append_logのテスト."""
        # callを作成
        ensure_call(db_session, call_id=test_call_id, client_id="test-client")
        
        # ログを追加
        request = AppendLogRequest(
            role="ai",
            text="AIメッセージ",
            state="greeting"
        )
        log = append_log(db_session, call_id=test_call_id, request=request)
        
        assert log is not None
        assert log.role == "ai"
        assert log.text == "AIメッセージ"
    
    def test_list_calls(self, db_session: Session):
        """list_callsのテスト."""
        # 複数のcallを作成
        for i in range(5):
            call_id = f"test-list-{i}"
            start_call(call_id, f"client-{i}", state="init")
        
        # 一覧を取得
        calls, total = list_calls(db_session, limit=10, offset=0)
        
        assert len(calls) == 5
        assert total == 5


class TestModels:
    """モデルのテスト."""
    
    def test_call_model(self, db_session: Session, test_call_id: str):
        """Callモデルのテスト."""
        call = Call(
            call_id=test_call_id,
            client_id="test-client",
            current_state="init"
        )
        db_session.add(call)
        db_session.commit()
        db_session.refresh(call)
        
        assert call.id is not None
        assert call.call_id == test_call_id
        assert call.started_at is not None
    
    def test_call_log_model(self, db_session: Session, test_call_id: str):
        """CallLogモデルのテスト."""
        # まずcallを作成
        call = Call(
            call_id=test_call_id,
            client_id="test-client"
        )
        db_session.add(call)
        db_session.commit()
        
        # ログを追加
        log = CallLog(
            call_id=test_call_id,
            role="user",
            text="テスト",
            state="init"
        )
        db_session.add(log)
        db_session.commit()
        db_session.refresh(log)
        
        assert log.id is not None
        assert log.call_id == test_call_id
        assert log.role == "user"
        assert log.timestamp is not None

