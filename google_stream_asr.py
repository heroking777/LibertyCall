#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Speech-to-Text Streaming API ラッパー
リアルタイム音声認識を提供
"""

from google.cloud import speech
import queue
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GoogleStreamingASR:
    """Google Speech-to-Text Streaming API ラッパークラス"""
    
    def __init__(self, language_code: str = "ja-JP", sample_rate: int = 16000):
        """
        Args:
            language_code: 言語コード（デフォルト: ja-JP）
            sample_rate: サンプリングレート（デフォルト: 16000Hz）
        """
        self.client = speech.SpeechClient()
        self.requests = queue.Queue()
        self.result_text: Optional[str] = None
        self.active = True
        self.language_code = language_code
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._stream_thread: Optional[threading.Thread] = None
        
        logger.info(f"[GoogleStreamingASR] Initialized (language={language_code}, sample_rate={sample_rate})")
    
    def add_audio(self, data: bytes):
        """音声データをASRストリームに追加"""
        if self.active and data:
            try:
                self.requests.put(data, block=False)
            except queue.Full:
                logger.warning("[GoogleStreamingASR] Queue full, dropping audio chunk")
    
    def start_stream(self):
        """ストリーミング認識を開始"""
        if self._stream_thread and self._stream_thread.is_alive():
            logger.warning("[GoogleStreamingASR] Stream already started")
            return
        
        def request_gen():
            """リクエストジェネレータ"""
            while self.active:
                try:
                    chunk = self.requests.get(timeout=1.0)
                    if chunk is None:
                        break
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                except queue.Empty:
                    # タイムアウト時は空のチャンクを送信して接続を維持
                    continue
                except Exception as e:
                    logger.error(f"[GoogleStreamingASR] Request generator error: {e}", exc_info=True)
                    break
        
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
        
        try:
            responses = self.client.streaming_recognize(streaming_config, request_gen())
            
            def process_responses():
                """レスポンス処理スレッド"""
                try:
                    for response in responses:
                        if not self.active:
                            break
                        for result in response.results:
                            if result.is_final_result:
                                with self._lock:
                                    self.result_text = result.alternatives[0].transcript
                                logger.info(f"[ASR] {self.result_text}")
                except Exception as e:
                    logger.error(f"[GoogleStreamingASR] Response processing error: {e}", exc_info=True)
            
            self._stream_thread = threading.Thread(target=process_responses, daemon=True)
            self._stream_thread.start()
            logger.info("[GoogleStreamingASR] Stream started")
        except Exception as e:
            logger.error(f"[GoogleStreamingASR] Failed to start stream: {e}", exc_info=True)
            self.active = False
    
    def has_input(self) -> bool:
        """認識結果があるかどうか"""
        with self._lock:
            return self.result_text is not None
    
    def get_text(self) -> Optional[str]:
        """認識結果テキストを取得（取得後はクリア）"""
        with self._lock:
            text = self.result_text
            self.result_text = None  # 取得後はクリア
            return text
    
    def stop(self):
        """ストリーミングを停止"""
        self.active = False
        try:
            self.requests.put(None, block=False)  # 終了シグナル
        except:
            pass
        logger.info("[GoogleStreamingASR] Stream stopped")

