"""FastAPIメインアプリケーション."""

from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .routers import logs_router
from .routers.sendgrid_webhook import router as sendgrid_webhook_router
from .routers import audio_tests
from .routers import calls
from .routers import flow
from .routers.auth import router as auth_router
from .routers.clients import router as clients_router
from .routers.users import router as users_router

settings = get_settings()

# FastAPIアプリケーション作成
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="LibertyCall管理画面用REST API",
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# APIルーター統合（フロントエンド配信より前に定義）
# logs_routerは既にprefix="/logs"を持っているので、settings.api_prefixのみ追加
app.include_router(logs_router, prefix=settings.api_prefix)
app.include_router(sendgrid_webhook_router, prefix=settings.api_prefix, tags=["sendgrid"])
app.include_router(audio_tests.router, prefix=settings.api_prefix)
app.include_router(calls.router, prefix=settings.api_prefix)
app.include_router(flow.router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(clients_router, prefix=settings.api_prefix)
app.include_router(users_router, prefix=settings.api_prefix)


@app.get("/")
def root():
    """ルートエンドポイント."""
    return {
        "message": "LibertyCall Console API is running.",
        "version": "1.0.0",
        "api_prefix": settings.api_prefix,
    }


@app.get("/health")
def health_check():
    """ヘルスチェックエンドポイント."""
    return {"status": "ok"}


@app.get("/healthz")
async def healthz_check():
    """軽量ヘルスチェックエンドポイント（監視統合用）."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
    }


# フロントエンドの配信（設定で有効な場合）
# 注意: このルートは最後に定義する必要がある（APIルートより後）
# ただし、APIパスは除外する必要があるため、条件を追加
# 一時的に無効化（APIが動作するか確認するため）
if False and settings.serve_frontend and settings.frontend_dir.exists():
    # 静的ファイルの配信
    app.mount("/static", StaticFiles(directory=str(settings.frontend_dir / "static")), name="static")
    
    # SPA用：すべてのパスでindex.htmlを返す（APIパスは除外）
    # 注意: FastAPIでは、より具体的なルートが先に評価されるため、
    # APIルートが先に定義されていれば、このルートはAPIパスにはマッチしない
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """フロントエンドを配信（SPA用）."""
        # APIパスは除外（/apiで始まるパスは除外）
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        
        index_file = settings.frontend_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        raise HTTPException(status_code=404, detail="Frontend not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "console_backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

