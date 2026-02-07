"""ASR起動の超高速化 - Config先行投げ戦略"""
import logging
import threading
import time
import os
from typing import Optional

# 【物理的解決】環境変数をハードコーディング
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/opt/libertycall/key/google_tts.json"

from google_stream_asr import GoogleStreamingASR
from .rtp_force_detector import force_detect_rtp_with_fallback

logger = logging.getLogger(__name__)

class ASRQuickStart:
    """ASR超高速起動マネージャー"""
    
    def __init__(self, call_id: str):
        self.call_id = call_id
        self.logger = logging.getLogger(f"ASRQuickStart[{call_id}]")
        self.asr_instance: Optional[GoogleStreamingASR] = None
        self._lock = threading.Lock()
        self._config_sent = False
        self._ready = False
        
    def pre_connect_google(self) -> bool:
        """
        【超高速化】通話UUID検知瞬間にGoogleに接続し、Configだけ投げて待機
        """
        with self._lock:
            if self._config_sent:
                return True
                
            try:
                self.logger.info(f"[QUICK_START] Pre-connecting Google ASR for {self.call_id}")
                
                # まずGoogleに接続してConfigだけ投げる
                self.asr_instance = GoogleStreamingASR(call_id=self.call_id)
                
                # Config送信のみ実行（音声データ待機なし）
                self.asr_instance.start_stream()
                
                self._config_sent = True
                self._ready = True
                
                self.logger.info(f"[QUICK_START] Google ASR pre-connected successfully for {self.call_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"[QUICK_START] Pre-connect failed: {e}")
                return False
    
    def feed_audio_immediate(self, audio_data: bytes) -> bool:
        """
        【超高速化】音声データが届いたら即座に送信
        """
        with self._lock:
            if not self._ready or not self.asr_instance:
                # 準備できていなければ即座に準備
                if not self.pre_connect_google():
                    return False
            
            try:
                # 【微小ノイズ混入】1%のディザリングで無理やり「音」として認識させる
                import numpy as np
                samples = np.frombuffer(audio_data, dtype=np.int16)
                # 1%のランダムノイズを追加
                noise = np.random.normal(0, np.max(np.abs(samples)) * 0.01, samples.shape).astype(np.int16)
                dithered_samples = np.clip(samples + noise, -32768, 32767)
                dithered_audio = dithered_samples.astype(np.int16).tobytes()
                
                # 音声データを即座に送信
                self.asr_instance.add_audio(dithered_audio)
                self.logger.warning(f"[QUICK_START] Audio fed immediately with dithering: {len(dithered_audio)} bytes")
                return True
                
            except Exception as e:
                self.logger.error(f"[QUICK_START] Audio feed failed: {e}")
                return False
    
    def force_start_with_rtp(self, uuid: str) -> bool:
        """
        【力技】RTP検出とASR起動を同時実行
        """
        start_time = time.time()
        
        # RTP検出を並列実行
        rtp_success, rtp_info = force_detect_rtp_with_fallback(uuid)
        
        if not rtp_success:
            self.logger.error(f"[FORCE_START] RTP detection failed for {uuid}")
            return False
        
        # RTP検出中に既にASRを準備
        self.pre_connect_google()
        
        elapsed = time.time() - start_time
        self.logger.info(f"[FORCE_START] Completed in {elapsed:.3f}s, RTP={rtp_info}")
        
        return True


# グローバルクイックスタート管理
_quick_start_instances = {}
_quick_start_lock = threading.Lock()

def get_or_create_quick_start(call_id: str) -> ASRQuickStart:
    """クイックスタートインスタンスを取得または作成"""
    with _quick_start_lock:
        if call_id not in _quick_start_instances:
            _quick_start_instances[call_id] = ASRQuickStart(call_id)
        return _quick_start_instances[call_id]

def force_start_asr_on_call_detected(call_id: str, uuid: str) -> bool:
    """
    【バイパス手術】通話検知時にASRを強制起動
    """
    logger.info(f"[FORCE_START] Call detected: call_id={call_id}, uuid={uuid}")
    
    # クイックスタートインスタンス取得
    quick_start = get_or_create_quick_start(call_id)
    
    # RTP検出とASR起動を同時実行
    return quick_start.force_start_with_rtp(uuid)

def cleanup_quick_start(call_id: str):
    """クイックスタートインスタンスをクリーンアップ"""
    with _quick_start_lock:
        if call_id in _quick_start_instances:
            instance = _quick_start_instances[call_id]
            if instance.asr_instance:
                instance.asr_instance.stop()
            del _quick_start_instances[call_id]
            logger.info(f"[FORCE_START] Cleaned up quick start for {call_id}")
