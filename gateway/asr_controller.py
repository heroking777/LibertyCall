"""
Gateway用ASR制御APIサーバー

FreeSWITCHからの通知を受けてASRストリーミングを開始するREST APIを提供
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional

logger = logging.getLogger(__name__)

# グローバル変数: RealtimeGatewayインスタンスへの参照
# realtime_gateway.pyのmain()で設定される
_gateway_instance: Optional[object] = None


def set_gateway_instance(gateway):
    """RealtimeGatewayインスタンスを設定"""
    global _gateway_instance
    _gateway_instance = gateway
    logger.info("ASR Controller: Gateway instance set")


app = FastAPI(
    title="LibertyCall Gateway ASR Controller",
    version="1.0.0",
    description="ASR起動制御用REST API"
)


@app.post("/asr/start/{uuid}")
async def start_asr(uuid: str):
    """
    ASRストリーミングを開始する
    
    :param uuid: 通話UUID（FreeSWITCHのcall UUID）
    :return: ステータスレスポンス
    """
    if not _gateway_instance:
        logger.error(f"start_asr: Gateway instance not set (uuid={uuid})")
        raise HTTPException(
            status_code=503,
            detail="Gateway instance not initialized"
        )
    
    try:
        # AICoreのenable_asr()を呼び出す
        ai_core = getattr(_gateway_instance, 'ai_core', None)
        if not ai_core:
            logger.error(f"start_asr: ai_core not found in gateway (uuid={uuid})")
            raise HTTPException(
                status_code=503,
                detail="AI Core not available"
            )
        
        # ASRを有効化
        ai_core.enable_asr(uuid)
        
        logger.info(f"ASR_START_API: uuid={uuid} status=ok")
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "uuid": uuid}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"start_asr: Failed to enable ASR (uuid={uuid}): {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enable ASR: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """ヘルスチェックエンドポイント"""
    return {"status": "ok", "gateway_available": _gateway_instance is not None}

