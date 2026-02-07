"""ASR audio processing - RAW VERSION (全加工禁止)"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ASRAudioProcessorRaw:
    """🔥 全加工禁止 - RTPデータをそのまま転送"""
    
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def extract_rtp_payload(self, data: bytes) -> bytes:
        """
        🔥 全加工禁止 - RTPペイロードをそのまま返す
        FreeSWITCHから届いたデータを一切加工せずに転送
        """
        if len(data) >= 12:
            # RTPヘッダーを除去してペイロードをそのまま返す
            payload = data[12:]
            self.logger.warning(f"[RAW_PAYLOAD] Size={len(payload)} bytes - NO PROCESSING")
            return payload
        else:
            self.logger.warning(f"[RAW_PAYLOAD] Too short data: {len(data)} bytes")
            return data

    def log_rtp_payload_debug(self, pcm_data: bytes, effective_call_id: Optional[str]) -> None:
        """🔥 デバッグも最小限 - サイズだけ記録"""
        self.logger.info(f"[RAW_DEBUG] call_id={effective_call_id} size={len(pcm_data)}")

    def _is_silent_l16(self, data: bytes, threshold: float = 0.005) -> bool:
        """🔥 無音判定もしない - 常にFalseを返す"""
        return False

    def update_vad_state(self, effective_call_id: str, pcm_data: bytes) -> Tuple[float, bool]:
        """🔥 VADも無効 - 常に有音と判定"""
        return 1000.0, True  # 常に高RMS・有音

    def process_pcm_payload(self, pcm_data: bytes, effective_call_id: str) -> Tuple[bytes, int]:
        """🔥 PCM処理も無効 - そのまま返す"""
        return pcm_data, len(pcm_data)
