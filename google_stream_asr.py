#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Speech-to-Text Streaming API ラッパー

音声ストリームをリアルタイムで認識し、テキスト結果を返す。
"""

from google.cloud import speech
import queue
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GoogleStreamingASR:
    """Google Speech-to-Text Streaming API ラッパー"""
    
    def __init__(self, language_code: str = "ja-JP", sample_rate: int = 16000):
        """
        初期化
        
        Args:
            language_code: 言語コード（デフォルト: ja-JP）
            sample_rate: サンプリングレート（デフォルト: 16000Hz）
        """
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.client = speech.SpeechClient()
        self.requests = queue.Queue()
        self.result_text: Optional[str] = None
        self.active = True
        self.lock = threading.Lock()
        self._response_thread: Optional[threading.Thread] = None
        
        logger.info(f"[GoogleStreamingASR] Initialized (language={language_code}, sample_rate={sample_rate}Hz)")
    
    def add_audio(self, data: bytes):
        """
        音声データを追加
        
        Args:
            data: PCM16形式の音声データ（16kHz, 16bit, モノラル）
        """
        if self.active and data:
            try:
                self.requests.put(data, timeout=0.1)
            except queue.Full:
                logger.warning("[GoogleStreamingASR] Queue full, dropping audio chunk")
    
    def start_stream(self):
        """ストリーミング認識を開始"""
        if self._response_thread and self._response_thread.is_alive():
            logger.warning("[GoogleStreamingASR] Stream already started")
            return
        
        def request_generator():
            """リクエスト生成ジェネレータ"""
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language_code,
                enable_automatic_punctuation=True
            )
            
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=False,
                single_utterance=False
            )
            
            # 最初に設定を送信
            yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)
            
            # 音声データを送信
            while self.active:
                try:
                    chunk = self.requests.get(timeout=1.0)
                    if chunk is None:
                        break
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                except queue.Empty:
                    # タイムアウト時は空のチャンクを送信（ストリーム維持）
                    continue
                except Exception as e:
                    logger.error(f"[GoogleStreamingASR] Error in request generator: {e}")
                    break
        
        def process_responses():
            """レスポンス処理スレッド"""
            try:
                responses = self.client.streaming_recognize(request_generator())
                
                for response in responses:
                    if not self.active:
                        break
                    
                    for result in response.results:
                        if result.is_final_result:
                            with self.lock:
                                self.result_text = result.alternatives[0].transcript
                            logger.info(f"[ASR] {self.result_text}")
            except Exception as e:
                logger.error(f"[GoogleStreamingASR] Error processing responses: {e}", exc_info=True)
            finally:
                self.active = False
        
        self._response_thread = threading.Thread(target=process_responses, daemon=True)
        self._response_thread.start()
        logger.info("[GoogleStreamingASR] Stream started")
    
    def has_input(self) -> bool:
        """
        認識結果があるかどうか
        
        Returns:
            bool: 認識結果がある場合True
        """
        with self.lock:
            return self.result_text is not None
    
    def get_text(self) -> Optional[str]:
        """
        認識結果テキストを取得
        
        Returns:
            str: 認識結果テキスト（未認識の場合はNone）
        """
        with self.lock:
            return self.result_text
    
    def reset(self):
        """認識結果をリセット"""
        with self.lock:
            self.result_text = None
        logger.debug("[GoogleStreamingASR] Result reset")
    
    def stop(self):
        """ストリーミングを停止"""
        self.active = False
        # キューにNoneを送ってジェネレータを終了させる
        try:
            self.requests.put(None, timeout=1.0)
        except queue.Full:
            pass
        
        if self._response_thread and self._response_thread.is_alive():
            self._response_thread.join(timeout=5.0)
        
        logger.info("[GoogleStreamingASR] Stream stopped")

