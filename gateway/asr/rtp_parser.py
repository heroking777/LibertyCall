"""RTPヘッダ解析ロジック"""
from __future__ import annotations

import struct
from typing import Tuple, Optional


class RTPParser:
    """RTPパケットのヘッダーを解析するユーティリティ"""
    
    @staticmethod
    def extract_rtp_payload(data: bytes) -> bytes:
        """
        RTPパケットからペイロードを抽出
        
        Args:
            data: RTPパケット（ヘッダー12バイト + ペイロード）
            
        Returns:
            ペイロードデータ
        """
        if len(data) < 12:
            return b''
        
        # RTPヘッダーをスキップ（12バイト）
        return data[12:]
    
    @staticmethod
    def parse_rtp_header(data: bytes) -> Optional[dict]:
        """
        RTPヘッダーを解析
        
        Args:
            data: RTPパケット
            
        Returns:
            ヘッダー情報の辞書
        """
        if len(data) < 12:
            return None
        
        # RTPヘッダー解析
        version = (data[0] >> 6) & 0x03
        padding = (data[0] >> 5) & 0x01
        extension = (data[0] >> 4) & 0x01
        csrc_count = data[0] & 0x0f
        marker = (data[1] >> 7) & 0x01
        payload_type = data[1] & 0x7f
        sequence = struct.unpack("!H", data[2:4])[0]
        timestamp = struct.unpack("!I", data[4:8])[0]
        ssrc = struct.unpack("!I", data[8:12])[0]
        
        return {
            'version': version,
            'padding': padding,
            'extension': extension,
            'csrc_count': csrc_count,
            'marker': marker,
            'payload_type': payload_type,
            'sequence': sequence,
            'timestamp': timestamp,
            'ssrc': ssrc,
        }
