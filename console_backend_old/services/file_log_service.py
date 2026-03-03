"""ファイルログサービス - 通話ログをファイルに書き込む."""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging

from ..models import Call, CallLog
from ..config import Settings


logger = logging.getLogger(__name__)


def append_log(
    call: Call,
    log: CallLog,
    settings: Settings,
    template_id: Optional[str] = None,
) -> None:
    """
    通話ログをファイルに追記.
    
    Args:
        call: 通話情報
        log: ログエントリ
        settings: アプリケーション設定
        template_id: テンプレートID（AIログの場合）
    """
    try:
        # ログベースディレクトリを取得
        logs_base_dir = settings.logs_base_dir
        
        # クライアントディレクトリを作成
        client_dir = logs_base_dir / call.client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイルパスを構築
        log_file = client_dir / f"{call.call_id}.log"
        
        # タイムスタンプをJSTに変換（UTCから+9時間）
        timestamp = log.timestamp
        if timestamp.tzinfo is None:
            # タイムゾーン情報がない場合はUTCとして扱う
            from datetime import UTC
            timestamp = timestamp.replace(tzinfo=UTC)
        
        # JSTに変換（UTC+9）
        jst_timestamp = timestamp.astimezone()
        timestamp_str = jst_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        
        # caller_numberを取得（callから取得、なければ"-"）
        caller_number = call.caller_number or "-"
        
        # ログ行を構築
        role_upper = log.role.upper()
        
        # 特別なstate（handoff_fail等）の処理
        if log.state == "handoff_fail":
            # handoff_failの場合は特別なフォーマット
            line = f"[{timestamp_str}] [{caller_number}] AI ({log.state}) {log.text}\n"
        elif role_upper == "AI" and template_id:
            # AIログでテンプレートIDがある場合
            line = f"[{timestamp_str}] [{caller_number}] AI (tpl={template_id}) {log.text}\n"
        elif role_upper == "AI" and log.state and log.state != "normal":
            # AIログでstateが特殊な場合（例: handoff_fail以外の特殊state）
            line = f"[{timestamp_str}] [{caller_number}] AI ({log.state}) {log.text}\n"
        else:
            # 通常のログ（USERまたは通常のAI）
            line = f"[{timestamp_str}] [{caller_number}] {role_upper} {log.text}\n"
        
        # ファイルに追記
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
        
        logger.debug(f"File log written: {log_file} (call_id={call.call_id})")
        
    except Exception as e:
        # ファイル書き込みエラーは通話処理を止めない
        logger.exception(f"Failed to write file log (call_id={call.call_id}): {e}")

