"""
セッション管理ユーティリティ関数

通話セッションの保存、ディレクトリ管理、ログ記録を担当
"""

import json
import logging
import os
import stat
import wave
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from .text_utils import TEMPLATE_CONFIG, normalize_text
from .state_store import get_session_state

logger = logging.getLogger(__name__)


def get_session_dir(call_id: str, client_id: Optional[str] = None) -> Path:
    """
    セッション保存ディレクトリのパスを取得
    
    :param call_id: 通話UUID
    :param client_id: クライアントID（指定がない場合はデフォルト）
    :return: セッションディレクトリのパス
    """
    if not client_id:
        client_id = "000"
    
    # 日付ベースのディレクトリ構造
    date_str = datetime.now().strftime("%Y-%m-%d")
    session_dir = Path(f"/var/lib/libertycall/sessions/{date_str}/{client_id}/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{call_id[:8]}")
    
    return session_dir


def ensure_session_dir(session_dir: Path) -> None:
    """
    セッションディレクトリを作成し、適切な権限を設定
    
    :param session_dir: 作成するディレクトリのパス
    :raises OSError: ディレクトリ作成に失敗した場合
    """
    try:
        # 親ディレクトリも含めて作成
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # 権限設定（所有者:読書書込、グループ:読書、その他:読書）
        session_dir.chmod(0o755)
        
        logger.info(f"セッションディレクトリを作成しました: {session_dir}")
        
    except OSError as e:
        logger.error(f"セッションディレクトリの作成に失敗しました: {session_dir}, エラー: {e}")
        raise


def save_transcript_event(call_id: str, text: str, is_final: bool, kwargs: dict, client_id: Optional[str] = None) -> None:
    """
    音声認識結果をトランスクリプトファイルに保存
    
    :param call_id: 通話UUID
    :param text: 認識されたテキスト
    :param is_final: 確定結果かどうか
    :param kwargs: 追加情報
    :param client_id: クライアントID
    """
    try:
        session_dir = get_session_dir(call_id, client_id)
        ensure_session_dir(session_dir)
        
        # トランスクリプトファイル
        transcript_file = session_dir / "transcript.jsonl"
        
        # イベントデータの作成
        event = {
            "timestamp": datetime.now().isoformat(),
            "call_id": call_id,
            "text": text,
            "is_final": is_final,
            **kwargs
        }
        
        # ファイルに追記
        with open(transcript_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
            
        logger.debug(f"トランスクリプトを保存しました: {call_id}, text={text[:50]}...")
        
    except Exception as e:
        logger.exception(f"トランスクリプトの保存に失敗しました: {e}")


def save_session_summary(call_id: str, summary_data: Dict[str, Any], client_id: Optional[str] = None) -> None:
    """
    セッション終了時にsummary.jsonを保存
    
    :param call_id: 通話UUID
    :param summary_data: 保存するサマリーデータ
    :param client_id: クライアントID
    """
    try:
        session_dir = get_session_dir(call_id, client_id)
        
        logger.error(f"!!! FORCE_MKDIR_AND_SAVE_SUMMARY_TO: {session_dir} !!!")
        ensure_session_dir(session_dir)
        
        summary_file = session_dir / "summary.json"
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        
        # サマリーデータにタイムスタンプを追加
        summary_data["ended_at"] = datetime.now().isoformat()
        summary_data["call_id"] = call_id
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"セッションサマリーを保存しました: {call_id} -> {summary_file}")
        
    except Exception as e:
        logger.exception(f"セッションサマリーの保存に失敗しました: {e}")
        raise


def append_call_log(call_id: str, role: str, text: str, template_id: Optional[str] = None, client_id: Optional[str] = None) -> None:
    """
    通話ログに1行追記
    
    :param call_id: 通話UUID
    :param role: 発話者（user/ai/system）
    :param text: 発話内容
    :param template_id: 使用したテンプレートID（AI発話の場合）
    :param client_id: クライアントID
    """
    try:
        session_dir = get_session_dir(call_id, client_id)
        ensure_session_dir(session_dir)
        
        # ログファイル
        log_file = session_dir / "call_log.txt"
        
        # ログ行の作成
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {role}: {text}"
        if template_id:
            log_line += f" (template: {template_id})"
        log_line += "\n"
        
        # ファイルに追記
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)
            
        logger.debug(f"通話ログを追記しました: {call_id}, {role}={text[:50]}...")
        
    except Exception as e:
        logger.exception(f"通話ログの追記に失敗しました: {e}")


def append_call_log_entry(core, role: str, text: str, template_id: Optional[str] = None) -> None:
    """
    AICoreの状態を参照して通話ログに1行追記
    """
    try:
        call_id = getattr(core, "call_id", None)
        client_id = getattr(core, "client_id", "000") or "000"

        if not call_id or str(call_id).lower() in ("unknown", "temp_call"):
            if not getattr(core, "log_session_id", None):
                now = datetime.now()
                core.log_session_id = now.strftime("CALL_%Y%m%d_%H%M%S%f")
            call_id = core.log_session_id

        append_call_log(str(call_id), role, text, template_id, client_id)
    except Exception as e:
        core.logger.exception(f"CALL_LOGGING_ERROR in append_call_log_entry: {e}")


def log_ai_templates(core, template_ids: List[str]) -> None:
    """AI応答テンプレートをログに記録"""
    try:
        for tid in template_ids:
            cfg = TEMPLATE_CONFIG.get(tid)
            if cfg and cfg.get("text"):
                append_call_log_entry(core, "AI", cfg["text"], template_id=tid)
    except Exception as e:
        core.logger.exception(f"CALL_LOGGING_ERROR (AI): {e}")


def save_session_summary_from_core(core, call_id: str) -> None:
    """AICoreのセッション情報からsummary.jsonを保存"""
    try:
        session_info = core.session_info.get(call_id, {})
        state = get_session_state(core, call_id)
        client_id = (
            core.call_client_map.get(call_id)
            or state.meta.get("client_id")
            or core.client_id
            or "000"
        )

        start_time = session_info.get("start_time", datetime.now())
        end_time = datetime.now()

        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        elif not isinstance(start_time, datetime):
            start_time = datetime.now()

        phrases = session_info.get("phrases", [])
        intents = []
        for phrase in phrases:
            text = phrase.get("text", "")
            if text:
                normalized = normalize_text(text)
                intent = "UNKNOWN"
                if intent and intent not in intents:
                    intents.append(intent)

        handoff_occurred = (
            state.transfer_requested
            or state.handoff_completed
            or state.phase == "HANDOFF_DONE"
        )

        summary = {
            "client_id": client_id,
            "uuid": call_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "total_phrases": len(phrases),
            "intents": intents,
            "handoff_occurred": handoff_occurred,
            "final_phase": state.phase or "UNKNOWN",
        }

        save_session_summary(call_id, summary, client_id)
        core.logger.info(
            "[SESSION_SUMMARY] Saved session summary: call_id=%s client_id=%s",
            call_id,
            client_id,
        )

        core.session_info.pop(call_id, None)
    except Exception as e:
        core.logger.exception(f"[SESSION_SUMMARY] Failed to save session summary: {e}")


def save_debug_wav(core, pcm16k_bytes: bytes) -> None:
    """Whisperに渡す直前のPCM音声をWAVファイルとして保存"""
    if not core.debug_save_wav:
        return

    sample_rate = 16000
    duration_sec = len(pcm16k_bytes) / 2 / sample_rate

    if duration_sec < 1.0:
        return

    debug_dir = Path("/opt/libertycall/debug_audio")
    debug_dir.mkdir(parents=True, exist_ok=True)

    call_id_str = core.call_id or "unknown"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    core._wav_chunk_counter += 1
    filename = f"call_{call_id_str}_chunk_{core._wav_chunk_counter:03d}_{timestamp}.wav"
    filepath = debug_dir / filename

    try:
        with wave.open(str(filepath), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm16k_bytes)
        logger.info("Saved debug WAV: %s (duration=%.2fs)", filepath, duration_sec)
    except Exception as e:
        logger.exception("Failed to save debug WAV: %s", e)


def save_transcript_event_from_core(core, call_id: str, text: str, is_final: bool, kwargs: dict) -> None:
    """Save transcript events and update in-memory session info for AICore."""
    try:
        client_id = getattr(core, "client_id", "000")
        save_transcript_event(call_id, text, is_final, kwargs, client_id)

        if call_id not in core.session_info:
            core.session_info[call_id] = {
                "start_time": datetime.now(),
                "intents": [],
                "phrases": [],
            }

        if is_final and text:
            session_info = core.session_info[call_id]
            session_info["phrases"].append({
                "text": text,
                "timestamp": datetime.now().isoformat(),
            })

        core.logger.debug(
            "[SESSION_LOG] Saved transcript event: call_id=%s is_final=%s",
            call_id,
            is_final,
        )
    except Exception as exc:
        core.logger.exception("[SESSION_LOG] Failed to save transcript event: %s", exc)


def cleanup_stale_sessions(max_age_days: int = 30) -> None:
    """
    古いセッションディレクトリをクリーンアップ
    
    :param max_age_days: 保持する最大日数
    """
    try:
        sessions_root = Path("/var/lib/libertycall/sessions")
        if not sessions_root.exists():
            return
        
        cutoff_date = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
        
        for date_dir in sessions_root.iterdir():
            if not date_dir.is_dir():
                continue
                
            try:
                dir_time = date_dir.stat().st_mtime
                if dir_time < cutoff_date:
                    import shutil
                    shutil.rmtree(date_dir)
                    logger.info(f"古いセッションディレクトリを削除しました: {date_dir}")
            except Exception as e:
                logger.warning(f"セッションディレクトリの削除に失敗しました: {date_dir}, エラー: {e}")
                
    except Exception as e:
        logger.exception(f"セッションクリーンアップ中にエラーが発生しました: {e}")
