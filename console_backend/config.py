"""設定管理モジュール."""

from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """アプリケーション設定."""
    
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),  # 絶対パスで指定（Webルート外）
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # .envファイルの他の設定を無視
    )
    
    # アプリケーション設定
    app_name: str = "LibertyCall Console API"
    api_prefix: str = "/api"
    
    # データベース設定
    database_url: str = "sqlite:///call_console.db"
    db_echo: bool = False
    
    # CORS設定
    cors_allow_origins: list[str] = ["*"]
    
    # WebSocket設定
    ws_path: str = "/ws/call-events"
    
    # 認証設定
    auth_enabled: bool = False
    JWT_SECRET_KEY: str = "change-this-secret-key-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    
    # 管理者設定
    admin_username: str = "admin"
    admin_password: str = "admin"
    
    # フロントエンド設定
    serve_frontend: bool = True
    frontend_dir: Path = Path(__file__).parent.parent / "frontend" / "build"
    
    # ログディレクトリ設定
    logs_base_dir: Path = Path("/opt/libertycall/logs/calls")
    
    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """データベースURLを検証・正規化."""
        if v.startswith("sqlite:///"):
            # 相対パスの場合は絶対パスに変換
            db_path = v.replace("sqlite:///", "")
            if not Path(db_path).is_absolute():
                project_root = Path(__file__).parent.parent
                db_path = str(project_root / db_path)
            return f"sqlite:///{db_path}"
        return v


@lru_cache()
def get_settings() -> Settings:
    """設定を取得（キャッシュ付き）."""
    return Settings()

