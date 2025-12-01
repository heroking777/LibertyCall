"""データベース接続管理モジュール."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from .config import get_settings

settings = get_settings()

# SQLAlchemyエンジン作成
engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

# セッション作成
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

# ベースクラス
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """データベースセッションを取得."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

