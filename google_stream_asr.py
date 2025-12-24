#!/usr/bin/env python3
"""
Google Speech-to-Text Streaming API ラッパー

既存のLibertyCallシステムに統合するためのGoogle Streaming ASR実装
"""
import queue
import threading
import logging
from typing import Optional
from google.cloud import speech

logger = logging.getLogger(__name__)


class GoogleStreamingASR:
    """Google Speech-to-Text Streaming API ラッパークラス"""
    
    def __init__(self, language_code: str = "ja-JP", sample_rate: int = 16000):
        """
        初期化
        
        Args:
            language_code: 言語コード（デフォルト: ja-JP）
            sample_rate: サンプルレート（デフォルト: 16000Hz）
        """
        self.client = speech.SpeechClient()
        self.requests = queue.Queue()
        self.result_text: Optional[str] = None
        self.active = True
        self.language_code = language_code
        self.sample_rate = sample_rate
        self._stream_thread: Optional[threading.Thread] = None
        self._response_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        logger.info(f"[GoogleStreamingASR] Initialized (language={language_code}, sample_rate={sample_rate})")
    
    def add_audio(self, data: bytes):
        """
        音声データをキューに追加
        
        Args:
            data: PCM16音声データ（16kHz）
        """
        if not self.active:
            return
        
        if data and len(data) > 0:
            self.requests.put(data)
    
    def start_stream(self):
        """ストリーミング認識を開始"""
        if self._stream_thread and self._stream_thread.is_alive():
            logger.warning("[GoogleStreamingASR] Stream already started")
            return
        
        self.active = True
        self.result_text = None
        
        # ストリーミング設定
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
        
        # リクエストジェネレータ
        def request_gen():
            while self.active:
                try:
                    chunk = self.requests.get(timeout=1.0)
                    if chunk is None:
                        break
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                except queue.Empty:
                    # タイムアウト時は空のリクエストを送信（ストリーム維持）
                    continue
                except Exception as e:
                    logger.error(f"[GoogleStreamingASR] Error in request_gen: {e}")
                    break
        
        # ストリーミング認識を開始
        def start_recognition():
            try:
                responses = self.client.streaming_recognize(streaming_config, request_gen())
                
                for response in responses:
                    if not self.active:
                        break
                    
                    for result in response.results:
                        if result.is_final_result:
                            with self._lock:
                                self.result_text = result.alternatives[0].transcript
                                logger.info(f"[ASR] Final result: {self.result_text}")
                        else:
                            # 中間結果も記録（必要に応じて）
                            interim_text = result.alternatives[0].transcript
                            logger.debug(f"[ASR] Interim result: {interim_text}")
            except Exception as e:
                logger.error(f"[GoogleStreamingASR] Recognition error: {e}", exc_info=True)
                self.active = False
        
        # バックグラウンドスレッドで認識処理を実行
        self._response_thread = threading.Thread(target=start_recognition, daemon=True)
        self._response_thread.start()
        
        logger.info("[GoogleStreamingASR] Stream started")
    
    def has_input(self) -> bool:
        """
        認識結果があるかチェック
        
        Returns:
            True: 認識結果あり / False: 認識結果なし
        """
        with self._lock:
            return self.result_text is not None
    
    def get_text(self) -> Optional[str]:
        """
        認識結果テキストを取得
        
        Returns:
            認識結果テキスト（Noneの場合は未認識）
        """
        with self._lock:
            return self.result_text
    
    def reset(self):
        """認識結果をリセット"""
        with self._lock:
            self.result_text = None
    
    def stop(self):
        """ストリーミングを停止"""
        self.active = False
        # 終了シグナルを送信
        self.requests.put(None)
        
        if self._response_thread and self._response_thread.is_alive():
            self._response_thread.join(timeout=5.0)
        
        logger.info("[GoogleStreamingASR] Stream stopped")

