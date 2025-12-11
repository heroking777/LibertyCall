#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
転送失敗時のTTSアナウンスをGateway経由で送信するスクリプト（簡易版）
GatewayのAICoreを直接呼び出してTTSを生成し、ログに記録
実際のRTP送信はGatewayが行う
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# TTSテキスト
HANDOFF_FAIL_TEXT = "現在、担当者の回線が込み合っております。こちらから折り返しご連絡いたしますので、このまま続けてお名前とご連絡先をお話しください。お話しが終わりましたら、そのまま電話をお切りください。"

def notify_gateway_handoff_fail(call_id: str = "TEMP_CALL"):
    """
    Gatewayに転送失敗を通知し、TTSアナウンスを要求
    
    注意: 現在の実装では、Gatewayが監視しているファイルにメッセージを書き込む
    将来的には、WebSocket APIまたはHTTP APIを使用する予定
    """
    try:
        logger.info(f"HANDOFF_FAIL_NOTIFY: call_id={call_id}")
        
        # Gatewayの通知ファイル（将来的に実装）
        notify_file = Path("/opt/libertycall/logs/gateway_notify.jsonl")
        
        # 通知メッセージ
        message = {
            "type": "handoff_fail",
            "call_id": call_id,
            "text": HANDOFF_FAIL_TEXT,
            "timestamp": datetime.now().isoformat(),
            "template_ids": None  # テンプレートIDは使用しない
        }
        
        # 通知ファイルに書き込む
        with open(notify_file, "a") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")
        
        logger.info(f"HANDOFF_FAIL_NOTIFY: Notification sent to Gateway")
        
        # ログにも記録
        call_log = Path(f"/opt/libertycall/logs/calls/000/{call_id}.log")
        if call_log.exists():
            with open(call_log, "a") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] [-] SYSTEM [HANDOFF_FAIL_TTS_REQUEST] text={HANDOFF_FAIL_TEXT!r}\n")
        
        return True
        
    except Exception as e:
        logger.exception(f"HANDOFF_FAIL_NOTIFY: Error: {e}")
        return False

if __name__ == "__main__":
    call_id = sys.argv[1] if len(sys.argv) > 1 else "TEMP_CALL"
    success = notify_gateway_handoff_fail(call_id)
    sys.exit(0 if success else 1)

