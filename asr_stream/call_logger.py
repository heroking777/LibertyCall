"""通話ログ記録モジュール（console_bridge連携付き）"""
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# console_bridge の安全なインポート
_bridge = None
try:
    import sys
    if '/opt/libertycall' not in sys.path:
        sys.path.insert(0, '/opt/libertycall')
    logger.info("[CALL_LOG] attempting console_bridge import...")
    from console_bridge import console_bridge as _bridge_instance
    logger.info("[CALL_LOG] console_bridge imported, enabled=%s, type=%s", 
                getattr(_bridge_instance, 'enabled', 'N/A'), type(_bridge_instance))
    if _bridge_instance and _bridge_instance.enabled:
        _bridge = _bridge_instance
        logger.info("[CALL_LOG] console_bridge ACTIVE, api=%s", _bridge_instance.api_base_url)
    else:
        logger.info("[CALL_LOG] console_bridge DISABLED (enabled=%s)", 
                    getattr(_bridge_instance, 'enabled', 'N/A'))
except Exception as e:
    import traceback
    logger.warning("[CALL_LOG] console_bridge import FAILED: %s\n%s", e, traceback.format_exc())


class CallLogger:
    def __init__(self, uuid: str, client_id: str = "000", caller_number: str = "番号不明"):
        self.uuid = uuid
        self.client_id = client_id
        self.caller_number = caller_number
        self.start_time = datetime.now(timezone.utc)

        date_str = self.start_time.strftime("%Y-%m-%d")
        self.base_dir = f"/opt/libertycall/recordings/{client_id}/{date_str}"
        os.makedirs(self.base_dir, exist_ok=True)

        self.jsonl_path = os.path.join(self.base_dir, f"{uuid}.jsonl")
        self._file = open(self.jsonl_path, "a", encoding="utf-8")

        self._write({"type": "call_start", "uuid": uuid,
                      "client_id": client_id})
        logger.info("[CALL_LOG] started uuid=%s path=%s", uuid, self.jsonl_path)

        # console_bridge: 通話開始
        if _bridge:
            try:
                _bridge.start_call(uuid, client_id, caller_number=caller_number)
            except Exception as e:
                logger.warning("[CALL_LOG] bridge start_call failed: %s", e)

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _write(self, record: dict):
        record.setdefault("time", self._now())
        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except Exception as e:
            logger.error("[CALL_LOG] write error uuid=%s err=%s", self.uuid, e)

    def _bridge_log(self, role: str, text: str, state: str = "active"):
        if _bridge:
            try:
                _bridge.append_log(self.uuid, role=role, text=text, state=state)
            except Exception as e:
                logger.warning("[CALL_LOG] bridge append_log failed: %s", e)
        else:
            pass

    def log_asr(self, text: str, is_final: bool, confidence: float = 0.0):
        self._write({
            "type": "asr_final" if is_final else "asr_interim",
            "text": text,
            "confidence": confidence,
        })
        if is_final and text.strip():
            pass  # USERログはlog_responseで先に記録済み

    def log_response(self, input_text: str, audio_ids: list,
                     phase: str):
        self._write({
            "type": "response",
            "text": input_text,
            "audio_ids": audio_ids,
            "phase": phase,
        })
        # USERの発話をAI応答より先にDB記録
        if input_text and input_text.strip():
            self._bridge_log("user", input_text, "active")

    def log_playback_start(self, audio_id: str, path: str, phrase: str = ""):
        self._write({
            "type": "playback_start",
            "audio_id": audio_id,
            "path": path,
        })
        # AI発話をDBに記録
        self._bridge_log("ai", phrase or audio_id, "active")

    def log_playback_end(self, audio_id: str, duration: float):
        self._write({
            "type": "playback_end",
            "audio_id": audio_id,
            "duration": round(duration, 3),
        })

    def log_action(self, action: str):
        self._write({"type": "action", "action": action})
        if action == "transfer":
            if _bridge:
                try:
                    _bridge.mark_transfer(self.uuid, "転送実行")
                except Exception as e:
                    logger.warning("[CALL_LOG] bridge mark_transfer failed: %s", e)
        self._bridge_log("system", f"action:{action}", "active")

    def close(self):
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        self._write({
            "type": "call_end",
            "uuid": self.uuid,
            "duration": round(elapsed, 1),
        })
        try:
            self._file.close()
        except Exception:
            pass
        logger.info("[CALL_LOG] closed uuid=%s duration=%.1fs", self.uuid, elapsed)
        # console_bridge: 通話終了
        if _bridge:
            try:
                _bridge.complete_call(self.uuid)
            except Exception as e:
                logger.warning("[CALL_LOG] bridge complete_call failed: %s", e)

    def get_recording_path(self) -> str:
        return os.path.join(self.base_dir, f"{self.uuid}.wav")
