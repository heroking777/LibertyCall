"""音声テスト結果APIルーター."""

import json
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/audio_tests", tags=["audio_tests"])

# プロジェクトルートを取得
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ASR_EVAL_RESULTS = PROJECT_ROOT / "logs" / "asr_eval_results.json"
CONVERSATION_TRACE_LOG = PROJECT_ROOT / "logs" / "conversation_trace.log"
HISTORY_DIR = PROJECT_ROOT / "logs" / "audio_test_history"


class ASRResultItem(BaseModel):
    """ASR評価結果アイテム."""
    file: str
    expected: str
    recognized: str
    wer: float
    status: str


class ASRSummary(BaseModel):
    """ASR評価サマリー."""
    total_samples: int
    avg_wer: float
    threshold: float
    status: str


class ASREvalResponse(BaseModel):
    """ASR評価レスポンス."""
    timestamp: str
    summary: ASRSummary
    results: List[ASRResultItem]


@router.get("/latest", response_model=ASREvalResponse)
async def get_latest_results():
    """最新のASR評価結果を取得."""
    if not ASR_EVAL_RESULTS.exists():
        raise HTTPException(
            status_code=404,
            detail="ASR evaluation results not found. Run asr_eval.py first."
        )
    
    try:
        with open(ASR_EVAL_RESULTS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ASREvalResponse(**data)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read ASR evaluation results: {str(e)}"
        )


@router.get("/history")
async def get_history(limit: int = 10):
    """ASR評価履歴を取得."""
    history_files = []
    
    # 履歴ディレクトリが存在する場合
    if HISTORY_DIR.exists():
        history_files = sorted(
            HISTORY_DIR.glob("asr_eval_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:limit]
    
    # 最新の結果も含める
    if ASR_EVAL_RESULTS.exists():
        history_files.insert(0, ASR_EVAL_RESULTS)
    
    results = []
    for file_path in history_files[:limit]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                results.append(data)
        except Exception as e:
            continue
    
    return {"history": results}


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """会話トレースログをWebSocketでストリーミング."""
    await websocket.accept()
    
    try:
        # 既存のログを送信
        if CONVERSATION_TRACE_LOG.exists():
            with open(CONVERSATION_TRACE_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 最後の50行を送信
                for line in lines[-50:]:
                    if line.strip():
                        await websocket.send_json({
                            "type": "log",
                            "data": line.strip()
                        })
        
        # ファイル監視（簡易版：ポーリング）
        import asyncio
        last_size = CONVERSATION_TRACE_LOG.stat().st_size if CONVERSATION_TRACE_LOG.exists() else 0
        
        while True:
            await asyncio.sleep(1)  # 1秒ごとにチェック
            
            if not CONVERSATION_TRACE_LOG.exists():
                continue
            
            current_size = CONVERSATION_TRACE_LOG.stat().st_size
            
            if current_size > last_size:
                # 新しい行を読み込む
                with open(CONVERSATION_TRACE_LOG, "r", encoding="utf-8") as f:
                    f.seek(last_size)
                    new_lines = f.readlines()
                    
                    for line in new_lines:
                        if line.strip():
                            await websocket.send_json({
                                "type": "log",
                                "data": line.strip()
                            })
                
                last_size = current_size
            
            # クライアントからのメッセージをチェック（ping/pong）
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except asyncio.TimeoutError:
                pass
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.close(code=1011, reason=str(e))

