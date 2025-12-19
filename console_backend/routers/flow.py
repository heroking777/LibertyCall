"""会話フロー管理APIルーター."""

from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flow", tags=["flow"])


@router.post("/reload")
async def reload_flow(
    client_id: str = Query(..., description="クライアントID"),
    request: Request = None
):
    """
    会話フローを保存してホットリロードする
    
    :param client_id: クライアントID（例: "000"）
    :param request: リクエストボディ（flow_dataを含む場合、保存してからリロード）
    :return: リロード結果
    """
    from fastapi import Request
    import json
    from pathlib import Path
    from datetime import datetime
    
    try:
        flow_path = Path(f"/opt/libertycall/config/clients/{client_id}/flow.json")
        flow_path.parent.mkdir(parents=True, exist_ok=True)
        
        # リクエストボディにflow_dataが含まれている場合は保存
        if request:
            try:
                body = await request.json()
                flow_data_str = body.get("flow_data")
                
                if flow_data_str:
                    # JSON文字列をパースして検証
                    flow_data = json.loads(flow_data_str)
                    
                    # updated_atを更新
                    flow_data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
                    
                    # ファイルに保存
                    with open(flow_path, "w", encoding="utf-8") as f:
                        json.dump(flow_data, f, ensure_ascii=False, indent=2)
                    
                    logger.info(f"[FLOW_SAVE] Saved flow.json for client_id={client_id}")
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
            except Exception as e:
                logger.exception(f"[FLOW_SAVE] Error: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to save flow: {str(e)}")
        
        logger.info(f"[FLOW_RELOAD_API] Request to reload flow for client_id={client_id}")
        
        # TODO: Gatewayインスタンスへのアクセス方法を実装
        # 現時点では、ファイル保存のみ実行
        return {
            "status": "success",
            "message": f"Flow for client_id={client_id} has been saved. "
                      "Gateway側でreload_flow()を実装する必要があります。",
            "client_id": client_id
        }
    except HTTPException:
        raise
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


@router.get("/content")
async def get_flow_content(client_id: str = Query(..., description="クライアントID")):
    """
    会話フローの内容（JSON）を取得する
    
    :param client_id: クライアントID（例: "000"）
    :return: フロー内容（JSON文字列）
    """
    import json
    from pathlib import Path
    
    flow_path = Path(f"/opt/libertycall/config/clients/{client_id}/flow.json")
    default_path = Path("/opt/libertycall/config/system/default_flow.json")
    
    # クライアント固有のファイルを優先、なければデフォルト
    target_path = flow_path if flow_path.exists() else default_path
    
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Flow file not found for client_id={client_id}")
    
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            flow = json.load(f)
        
        return {
            "client_id": client_id,
            "content": json.dumps(flow, ensure_ascii=False, indent=2),
            "version": flow.get("version", "unknown"),
            "updated_at": flow.get("updated_at", "unknown")
        }
    except Exception as e:
        logger.exception(f"[FLOW_CONTENT_API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

