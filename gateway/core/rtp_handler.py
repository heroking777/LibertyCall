"""RTPパケットハンドラー"""
from __future__ import annotations

import os
import sys
import traceback
from typing import Tuple

from ..asr.asr_manager import ASRManager


class RTPHandler:
    """RTPパケットの処理を担当"""
    
    def __init__(self, asr_manager: ASRManager):
        self.asr_manager = asr_manager
    
    async def handle_rtp_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
        """RTPパケットを非同期で処理"""
        os.write(2, b"[TRACE_RTP_HANDLER_ENTRY]\n")
        os.write(2, f"[TRACE_HANDLE_RTP] handle_rtp_packet called with {len(data)} bytes\n")
        
        if not hasattr(self, 'asr_manager') or self.asr_manager is None:
            os.write(2, b"[TRACE_HANDLE_RTP] ERROR: asr_manager is None\n")
            return
        
        try:
            self.asr_manager.process_rtp_audio(data, addr)
            os.write(2, b"[TRACE_HANDLE_RTP] process_rtp_audio completed\n")
        except Exception as e:
            os.write(2, f"[TRACE_HANDLE_RTP] ERROR: {e}\n")
            os.write(2, f"[TRACE_HANDLE_RTP] TRACEBACK: {traceback.format_exc()}\n")
