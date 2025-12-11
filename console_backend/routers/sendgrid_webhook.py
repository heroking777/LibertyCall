"""
SendGrid Event Webhook受信
SendGridから送信されるイベント（配信成功・バウンス・開封など）を受信して記録
"""

from fastapi import APIRouter, Request
import csv
from datetime import datetime
from pathlib import Path

router = APIRouter()


@router.post("/sendgrid/events")
async def handle_sendgrid_events(request: Request):
    """
    SendGrid Event Webhook受信
    受信イベントをCSVに記録する（バウンス・自動返信・開封など）
    
    SendGridから送信されるイベント例:
    - processed: メールが処理された
    - delivered: メールが配信された
    - bounce: バウンス（宛先エラー）
    - dropped: ドロップされた
    - spamreport: スパム報告
    - unsubscribe: 配信停止
    - open: メールが開封された
    - click: リンクがクリックされた
    - auto_reply: 自動返信
    """
    try:
        events = await request.json()
    except Exception as e:
        return {"status": "error", "message": f"Invalid JSON: {str(e)}"}
    
    # イベントが単一オブジェクトの場合はリストに変換
    if not isinstance(events, list):
        events = [events]
    
    # ログファイルのパス（プロジェクトルートのlogsディレクトリ）
    project_root = Path(__file__).parent.parent.parent
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "sendgrid_events.csv"
    
    # CSVファイルが存在しない場合はヘッダーを書き込む
    file_exists = log_path.exists()
    
    try:
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # ヘッダーを書き込む（ファイルが新規の場合のみ）
            if not file_exists:
                writer.writerow(["email", "event", "reason", "timestamp"])
            
            # イベントを記録
            for e in events:
                writer.writerow([
                    e.get("email", ""),
                    e.get("event", ""),
                    e.get("reason", ""),
                    datetime.utcnow().isoformat()
                ])
        
        return {"status": "ok", "count": len(events)}
    
    except Exception as e:
        return {"status": "error", "message": f"Failed to write log: {str(e)}"}

