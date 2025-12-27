#!/usr/bin/env python3
"""
Google Speech-to-Text Streaming API ラッパー

既存のLibertyCallシステムに統合するためのGoogle Streaming ASR実装
"""
import queue
import threading
import logging
from typing import Optional
from google.cloud.speech_v1p1beta1 import SpeechClient  # type: ignore
from google.cloud.speech_v1p1beta1.types import cloud_speech  # type: ignore

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
        self.client = SpeechClient()
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
        config = cloud_speech.RecognitionConfig(  # type: ignore[union-attr]
            encoding=cloud_speech.RecognitionConfig.AudioEncoding.LINEAR16,  # type: ignore[union-attr]
            sample_rate_hertz=self.sample_rate,
            language_code=self.language_code,
            enable_automatic_punctuation=True
        )
        
        streaming_config = cloud_speech.StreamingRecognitionConfig(  # type: ignore[union-attr]
            config=config,
            interim_results=False,
            single_utterance=False
        )
        logger.warning(f"[ASR_STREAM_INIT] StreamingRecognitionConfig created: interim={streaming_config.interim_results}, single_utterance={streaming_config.single_utterance}")
        
        # リクエストジェネレータ
        def request_gen():
            logger.info("[GOOGLE_ASR_REQUEST] Starting request generator, sending initial config")
            # 最初のリクエストにはstreaming_configを含める（必須）
            initial_request = cloud_speech.StreamingRecognizeRequest(streaming_config=streaming_config)  # type: ignore[union-attr]
            logger.info(f"[GOOGLE_ASR_REQUEST] Yielding initial request with streaming_config")
            yield initial_request
            
            request_count = 0
            # その後、音声データを送信
            while self.active:
                try:
                    chunk = self.requests.get(timeout=1.0)
                    logger.warning(f"[ASR_QUEUE_GET] Got audio chunk from queue, size={len(chunk) if chunk else 0}")
                    if chunk is None:
                        logger.info("[GOOGLE_ASR_REQUEST] Received None chunk, ending request generator")
                        break
                    request_count += 1
                    if request_count % 50 == 0:  # 50リクエストごとにログ出力
                        logger.info(f"[GOOGLE_ASR_REQUEST] Yielding audio chunk #{request_count}, size={len(chunk)} bytes")
                    logger.warning(f"[ASR_YIELD_REQUEST] Yielding audio request to Google ASR, chunk_size={len(chunk)}")
                    yield cloud_speech.StreamingRecognizeRequest(audio_content=chunk)  # type: ignore[union-attr]
                except queue.Empty:
                    # タイムアウト時は空のリクエストを送信（ストリーム維持）
                    # Google ASRは約5秒間音声が送られないとタイムアウトするため、
                    # 空のリクエストを送信してストリームを維持する
                    logger.debug("[GOOGLE_ASR_REQUEST] Queue empty, sending empty audio request to maintain stream")
                    yield cloud_speech.StreamingRecognizeRequest(audio_content=b'')  # type: ignore[union-attr]
                    continue
                except Exception as e:
                    logger.error(f"[GoogleStreamingASR] Error in request_gen: {e}", exc_info=True)
                    break
            
            logger.info(f"[GOOGLE_ASR_REQUEST] Request generator ended, total requests: {request_count}")
        
        # ストリーミング認識を開始
        def start_recognition():
            try:
                logger.info("[GOOGLE_ASR_STREAM] Starting streaming_recognize call")
                # streaming_recognize()のシグネチャ: (self, config, requests, ...)
                # configとrequestsを位置引数として渡す
                logger.warning(f"[ASR_STREAM_START] streaming_recognize started for call_id={getattr(self, 'call_id', 'unknown')}")
                logger.warning(f"[ASR_STREAM_ITER] Starting to iterate responses")
                responses = self.client.streaming_recognize(
                    config=streaming_config,
                    requests=request_gen()
                )
                logger.info("[GOOGLE_ASR_STREAM] streaming_recognize called, waiting for responses...")
                
                response_count = 0
                for response in responses:
                    logger.warning(f"[ASR_RESPONSE_RECEIVED] Response received from Google ASR")
                    logger.warning(f"[ASR_RESPONSE_TYPE] resp type={type(response)}")
                    logger.warning(f"[ASR_RESPONSE_HAS_RESULTS] has results={hasattr(response, 'results')} results_count={len(response.results) if hasattr(response, 'results') else 0}")
                    response_count += 1
                    logger.info(f"[GOOGLE_ASR_RESPONSE] Received response #{response_count}")
                    
                    if not self.active:
                        logger.info("[GOOGLE_ASR_RESPONSE] Active flag is False, breaking loop")
                        break
                    
                    logger.debug(f"[GOOGLE_ASR_RESPONSE] Response has {len(response.results)} results")
                    if hasattr(response, 'results') and response.results:
                        for i, result in enumerate(response.results):
                            logger.warning(f"[ASR_RESULT_{i}] is_final={result.is_final_result if hasattr(result, 'is_final_result') else 'N/A'} alternatives_count={len(result.alternatives) if hasattr(result, 'alternatives') else 0}")
                            if hasattr(result, 'alternatives') and result.alternatives:
                                for j, alt in enumerate(result.alternatives):
                                    logger.warning(f"[ASR_ALT_{i}_{j}] transcript='{alt.transcript}' confidence={getattr(alt, 'confidence', 'N/A')}")
                            if result.is_final_result:
                                with self._lock:
                                    self.result_text = result.alternatives[0].transcript
                                    logger.info(f"[ASR] Final result: {self.result_text}")
                            else:
                                # 中間結果も記録（必要に応じて）
                                interim_text = result.alternatives[0].transcript
                                logger.info(f"[ASR] Interim result: {interim_text}")
                
                if response_count == 0:
                    logger.warning("[GOOGLE_ASR_RESPONSE] No responses received from Google ASR")
            except Exception as e:
                logger.error(f"[ASR_WORKER_EXCEPTION] Exception type={type(e).__name__}")
                logger.error(f"[ASR_WORKER_EXCEPTION] Exception message={str(e)}")
                logger.error(f"[ASR_WORKER_EXCEPTION] Traceback:", exc_info=True)
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

