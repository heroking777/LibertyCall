"""会話フロー管理APIルーター."""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flow", tags=["flow"])


@router.post("/reload")
async def reload_flow(client_id: str = Query(..., description="クライアントID")):
    """
    会話フローをホットリロードする
    
    :param client_id: クライアントID（例: "000"）
    :return: リロード結果
    """
    try:
        # Gatewayインスタンスにアクセスする必要がある
        # 注意: Gatewayは別プロセスで動作しているため、直接アクセスは困難
        # 将来的には、GatewayとBackend間でIPC（共有メモリ、Unixソケット、Redis等）を実装する必要がある
        
        # 現時点では、Gateway側でreload_flow()を呼び出す方法を提供
        # 方法1: GatewayのWebSocket経由でリロードコマンドを送信
        # 方法2: Gatewayプロセスにシグナルを送信してリロードをトリガー
        
        logger.info(f"[FLOW_RELOAD_API] Request to reload flow for client_id={client_id}")
        
        # TODO: Gatewayインスタンスへのアクセス方法を実装
        # 現時点では、ログに記録するだけ
        return {
            "status": "accepted",
            "message": f"Flow reload request for client_id={client_id} has been logged. "
                      "Gateway側でreload_flow()を実装する必要があります。",
            "client_id": client_id
        }
    except Exception as e:
        logger.exception(f"[FLOW_RELOAD_API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_flow_status(client_id: str = Query(..., description="クライアントID")):
    """
    会話フローの状態を取得する
    
    :param client_id: クライアントID（例: "000"）
    :return: フロー状態
    """
    import json
    from pathlib import Path
    
    flow_path = Path(f"/opt/libertycall/config/clients/{client_id}/flow.json")
    
    if not flow_path.exists():
        raise HTTPException(status_code=404, detail=f"Flow file not found for client_id={client_id}")
    
    try:
        with open(flow_path, "r", encoding="utf-8") as f:
            flow = json.load(f)
        
        return {
            "client_id": client_id,
            "version": flow.get("version", "unknown"),
            "updated_at": flow.get("updated_at", "unknown"),
            "phases": list(flow.get("phases", {}).keys()),
            "flow_path": str(flow_path)
        }
    except Exception as e:
        logger.exception(f"[FLOW_STATUS_API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

