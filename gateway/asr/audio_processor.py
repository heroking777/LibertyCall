"""AudioProcessor - 音声処理モジュール"""
from __future__ import annotations

import logging
import os
import traceback
import time
from typing import Tuple

# NOTE: 診断用。リアルタイム待機は禁止のため、ファイルへ一発書きのみ。
_RTP_DUMP_TRACE = "/tmp/rtp_dump_trace.log"
_TRACE_ONCE_KEYS = set()

def _trace_once(key: str, msg: str) -> None:
    try:
        if key in _TRACE_ONCE_KEYS:
            return
        _TRACE_ONCE_KEYS.add(key)
        with open(_RTP_DUMP_TRACE, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} {msg}\n")
    except Exception:
        # 診断は本処理を壊さない
        return

_trace_once("module_loaded", f"[audio_processor] module_loaded pid={os.getpid()} LC_RTP_DUMP={os.environ.get('LC_RTP_DUMP','')}")

TRACE_FD = os.open("/tmp/audio_processor.trace", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
TRACE_FD2 = os.open("/tmp/gateway_asr_audio_processor.trace", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

os.write(TRACE_FD2, b"[TRACE_PROC_LOAD] Imports successful\n")

import numpy as np
import math
import struct
import sys
from typing import Optional

from ..audio.rtp_payload_dumper import RtpPayloadDumper

logger = logging.getLogger(__name__)


class AudioProcessor:
    """音声データの処理を行う"""
    
    def __init__(self, call_id: str = "unknown", sample_rate: int = 16000):
        self.call_id = call_id
        self.sample_rate = sample_rate
        self.logger = logging.getLogger(__name__)
        self.rtp_dumper = RtpPayloadDumper(call_uuid=str(call_id))
        _trace_once("dumper_init", f"[audio_processor] dumper_init pid={os.getpid()} uuid={call_id} enabled={self.rtp_dumper.enabled}")
        self._rtp_dump_call_count = 0
        self._last_voice_time = {}
        self._last_silence_time = {}
        self._voice_threshold = 0.01  # RMS閾値
    
    def calculate_rms(self, data: bytes) -> float:
        """RMSを計算"""
        if not data:
            return 0.0
        
        # bytesをnumpy配列に変換
        try:
            # 16bit PCMを想定
            samples = np.frombuffer(data, dtype=np.int16)
            if len(samples) == 0:
                return 0.0
            
            # RMSを計算
            rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
            return rms / 32768.0  # 正規化
        except Exception as e:
            logger.error(f"[AudioProcessor] RMS calculation error: {e}")
            return 0.0
    
    def is_voice(self, rms: float) -> bool:
        """音声かどうかを判定"""
        os.write(TRACE_FD, f"[TRACE_AP_ID] id={id(self)}\n".encode())
        os.write(TRACE_FD, f"[TRACE_VAD_PRE] bytes=unknown rms={rms} threshold={self._voice_threshold}\n".encode())
        
        is_voice = rms >= self._voice_threshold
        
        if is_voice:
            os.write(TRACE_FD, b"[TRACE_VAD_DECISION] ACCEPT\n")
        else:
            os.write(TRACE_FD, b"[TRACE_VAD_DECISION] REJECT\n")
        
        return is_voice
    
    def extract_rtp_payload(self, data: bytes) -> bytes:
        """RTPパケットからペイロードを抽出"""
        if len(data) < 12:
            return b''
        
        # RTPヘッダーをスキップ（12バイト）
        return data[12:]
    
    def update_vad_state(self, call_id: str, data: bytes) -> tuple[bool, float]:
        """VAD状態を更新"""
        rms = self.calculate_rms(data)
        is_voice = self.is_voice(rms)
        
        current_time = time.time()
        
        if is_voice:
            self._last_voice_time[call_id] = current_time
        else:
            self._last_silence_time[call_id] = current_time
        
        return is_voice, rms
    
    def convert_to_pcm16k(self, data: bytes, source_sample_rate: int = 8000) -> bytes:
        """PCM8kHzをPCM16kHzに変換"""
        if source_sample_rate == 16000:
            return data
        
        # 簡単な補間（実際の実装ではもっと高度な変換が必要）
        try:
            samples = np.frombuffer(data, dtype=np.int16)
            
            # 2倍にリサンプリング
            resampled = np.repeat(samples, 2)
            
            return resampled.astype(np.int16).tobytes()
        except Exception as e:
            logger.error(f"[AudioProcessor] Resampling error: {e}")
            return data
    
    def log_rtp_payload_debug(self, pcm_data: bytes, call_id: str):
        """RTPペイロードのデバッグログ"""
        if not pcm_data:
            return
        
        # 【デバッグ】ペイロード先頭16バイトをダンプ
        payload_hex = pcm_data[:16].hex()
        logger.info(f"[RTP_PAYLOAD_DUMP] call_id={call_id} first_16_bytes={payload_hex}")
        
        # 無音データチェック（0x00や0xFFが連続する場合）
        if all(b == 0 for b in pcm_data[:16]):
            logger.warning("[RTP_PAYLOAD] Detected all-zero payload (silence)")
        elif all(b == 255 for b in pcm_data[:16]):
            logger.warning("[RTP_PAYLOAD] Detected all-0xFF payload (possible silence)")
        
        # RMSとVAD判定
        rms = self.calculate_rms(pcm_data)
        is_voice = self.is_voice(rms)
        logger.info(f"[RTP_VAD] call_id={call_id} rms={rms:.6f} is_voice={is_voice}")
        
        # デバッグ用に生データを保存
        try:
            import os
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            save_dir = "/opt/libertycall/audio_recordings"
            os.makedirs(save_dir, exist_ok=True)
            save_path = f"{save_dir}/rtp_payload_{call_id}_{timestamp}.raw"
            with open(save_path, "wb") as f:
                f.write(pcm_data)
            logger.info(f"[RTP_PAYLOAD_SAVE] Saved payload to {save_path}")
        except Exception as e:
            logger.error(f"[RTP_PAYLOAD_SAVE] Failed to save payload: {e}")
    
    def process_rtp_audio(self, data: bytes, addr: Tuple[str, int]) -> bytes:
        self._rtp_dump_call_count += 1
        if self._rtp_dump_call_count <= 3:
            _trace_once(f"process_called_{self._rtp_dump_call_count}", f"[audio_processor] process_rtp_audio_called n={self._rtp_dump_call_count} pid={os.getpid()} data_len={len(data)}")
        os.write(TRACE_FD2, b"[TRACE_PROC_1] Entry\n")
        try:
            payload = data[12:]  # RTP Header strip
            os.write(TRACE_FD2, b"[TRACE_PROC_2] Header stripped\n")
            
            # RTP受信直後payloadをダンプ（デコード前）
            try:
                self.rtp_dumper.feed(payload)
                if self._rtp_dump_call_count == 1:
                    _trace_once("feed_ok", f"[audio_processor] dumper_feed_ok pid={os.getpid()} payload_len={len(payload)}")
            except Exception as e:
                _trace_once("feed_err", f"[audio_processor] dumper_feed_err pid={os.getpid()} err={repr(e)}")
                # 診断で通話を壊さない
                pass

            # --- ここから例外が発生しやすい区間 ---
            # 例: PCM変換やVAD判定
            pcm_data = self.convert_to_pcm16k(payload)
            
            os.write(TRACE_FD2, b"[TRACE_PROC_VAD_START]\n")
            # RMSを計算してからis_voiceに渡す
            rms = self.calculate_rms(pcm_data)
            
            # PCM統計ログ（RMS計算前に実行）
            try:
                import struct
                samples = struct.unpack("<%dh" % (len(pcm_data) // 2), pcm_data)
                os.write(TRACE_FD2, f"[TRACE_PCM_STATS] samples={len(samples)} min={min(samples)} max={max(samples)}\n".encode())
            except BaseException as e:
                try:
                    os.write(TRACE_FD2, f"[TRACE_PCM_STATS_ERROR] {e}\n".encode())
                except BaseException:
                    pass
            
            # VAD判定直前の状態ログ
            os.write(TRACE_FD2, f"[TRACE_VAD_RMS] rms={rms:.6f}\n".encode())
            os.write(TRACE_FD2, f"[TRACE_VAD_THRESHOLD] threshold={self._voice_threshold}\n".encode())
            
            if self.is_voice(rms):
                os.write(TRACE_FD2, b"[TRACE_VAD_RESULT] result=True\n")
                os.write(TRACE_FD2, b"[TRACE_PROC_3] VAD OK\n")
                # VAD ACCEPT: 上流が None 判定しないよう、必ずデータを返す
                os.write(TRACE_FD2, (f"[TRACE_RET_PCM] len={len(pcm_data)}\n").encode())
                return pcm_data
            else:
                os.write(TRACE_FD2, b"[TRACE_VAD_RESULT] result=False\n".encode())
                os.write(TRACE_FD2, b"[TRACE_PROC_SILENCE] VAD rejected (silence)\n")
                os.write(TRACE_FD2, b"[TRACE_RET_NONE] reason=vad\n")
                return None
            # --- ここまで ---

        except Exception as e:
            import traceback
            os.write(TRACE_FD2, f"[TRACE_PROC_ERR] {e}\n{traceback.format_exc()}\n".encode())
            try:
                os.write(TRACE_FD2, f"[TRACE_RET_NONE] reason=exception {repr(e)}\n".encode())
                os.write(TRACE_FD2, b"[TRACE_EXC]\n")
                os.write(TRACE_FD2, traceback.format_exc().encode())
                os.write(TRACE_FD2, b"[TRACE_EXC_END]\n")
            except Exception:
                pass
            return None
    
    def cleanup(self):
        """クリーンアップ処理"""
        try:
            self.rtp_dumper.close()
            _trace_once("dumper_close", f"[audio_processor] dumper_close pid={os.getpid()}")
        except Exception as e:
            _trace_once("dumper_close_err", f"[audio_processor] dumper_close_err pid={os.getpid()} err={repr(e)}")
            pass
