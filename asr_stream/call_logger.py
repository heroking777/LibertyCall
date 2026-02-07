"""通話ログ記録モジュール"""
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class CallLogger:
    def __init__(self, uuid: str, client_id: str = "000"):
        self.uuid = uuid
        self.client_id = client_id
        self.start_time = datetime.now(timezone.utc)
        
        date_str = self.start_time.strftime("%Y-%m-%d")
        self.base_dir = f"/opt/libertycall/recordings/{client_id}/{date_str}"
        os.makedirs(self.base_dir, exist_ok=True)
        
        self.jsonl_path = os.path.join(self.base_dir, f"{uuid}.jsonl")
        self._file = open(self.jsonl_path, "a", encoding="utf-8")
        
        self._write({"type": "call_start", "uuid": uuid,
                      "client_id": client_id})
        logger.info("[CALL_LOG] started uuid=%s path=%s", uuid, self.jsonl_path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _write(self, record: dict):
        record.setdefault("time", self._now())
        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except Exception as e:
            logger.error("[CALL_LOG] write error uuid=%s err=%s", self.uuid, e)

    def log_asr(self, text: str, is_final: bool, confidence: float = 0.0):
        self._write({
            "type": "asr_final" if is_final else "asr_interim",
            "text": text,
            "confidence": confidence,
        })

    def log_response(self, input_text: str, audio_ids: list,
                     phase: str):
        self._write({
            "type": "response",
            "text": input_text,
            "audio_ids": audio_ids,
            "phase": phase,
        })

    def log_playback_start(self, audio_id: str, path: str):
        self._write({
            "type": "playback_start",
            "audio_id": audio_id,
            "path": path,
        })

    def log_playback_end(self, audio_id: str, duration: float):
        self._write({
            "type": "playback_end",
            "audio_id": audio_id,
            "duration": round(duration, 3),
        })

    def log_action(self, action: str):
        self._write({"type": "action", "action": action})

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

    # 録音ファイルパス生成（FreeSWITCH用）
    def get_recording_path(self) -> str:
        return os.path.join(self.base_dir, f"{self.uuid}.wav")
