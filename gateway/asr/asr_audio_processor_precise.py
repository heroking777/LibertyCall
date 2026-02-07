"""ASR audio processing - PRECISE VERSION (言い訳禁止)"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ASRAudioProcessorPrecise:
    """🔥 言い訳禁止 - 正確なRTPヘッダー解析"""
    
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def extract_rtp_payload(self, data: bytes) -> bytes:
        """
        🔥 RTPペイロードの「正確な」オフセット抽出
        RFC 3550に準拠した可変ヘッダー対応
        """
        if len(data) < 12:
            self.logger.warning(f"[PRECISE_RTP] Too short data: {len(data)} bytes")
            return data
        
        # 🔥 固定12バイトではなく、可変ヘッダーに対応
        version_flags = data[0]
        has_extension = (version_flags >> 4) & 0x01
        csrc_count = version_flags & 0x0F
        payload_offset = 12 + (csrc_count * 4)
        
        self.logger.warning(f"[PRECISE_RTP] V=2, X={has_extension}, CC={csrc_count}, base_offset=12")
        
        if has_extension:
            # 拡張ヘッダーがある場合、さらに4+len*4バイト飛ばす
            if len(data) < payload_offset + 4:
                self.logger.error(f"[PRECISE_RTP] Extension header incomplete")
                return data[12:]  # フォールバック
            
            ext_header_len = int.from_bytes(data[payload_offset+2:payload_offset+4], 'big')
            payload_offset += 4 + (ext_header_len * 4)
            
            self.logger.warning(f"[PRECISE_RTP] Extension found: len={ext_header_len}, final_offset={payload_offset}")
        
        if payload_offset >= len(data):
            self.logger.error(f"[PRECISE_RTP] Payload offset {payload_offset} exceeds data length {len(data)}")
            return data[12:]  # フォールバック
        
        audio_content = data[payload_offset:]
        
        # 🔥 バイナリ整合性チェック
        if len(audio_content) > 0:
            first_byte = audio_content[0]
            if first_byte in [0x80, 0x00]:
                self.logger.error(f"[PRECISE_RTP] HEADER STILL PRESENT! First byte=0x{first_byte:02x}")
                self.logger.error(f"[PRECISE_RTP] Offset calculation wrong - aborting send")
                return b''  # 送信中止
            else:
                self.logger.warning(f"[PRECISE_RTP] Clean payload: first_byte=0x{first_byte:02x}, size={len(audio_content)}")
        
        self.logger.warning(f"[PRECISE_RTP] Extracted {len(audio_content)} bytes at offset {payload_offset}")
        return audio_content

    def log_rtp_payload_debug(self, pcm_data: bytes, effective_call_id: Optional[str]) -> None:
        """🔥 デバッグも最小限"""
        if len(pcm_data) > 0:
            first_32 = pcm_data[:32].hex()
            self.logger.warning(f"[PRECISE_DEBUG] call_id={effective_call_id} first_32bytes={first_32}")

    def _is_silent_l16(self, data: bytes, threshold: float = 0.005) -> bool:
        """🔥 無音判定もしない"""
        return False

    def update_vad_state(self, effective_call_id: str, pcm_data: bytes) -> Tuple[float, bool]:
        """🔥 VADも無効"""
        return 1000.0, True

    def process_pcm_payload(self, pcm_data: bytes, effective_call_id: str) -> Tuple[bytes, int]:
        """🔥 PCM処理も無効 - そのまま返す"""
        return pcm_data, len(pcm_data)
