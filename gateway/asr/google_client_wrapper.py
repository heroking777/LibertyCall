"""Google Cloud Speech-to-Text クライアントラッパー"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Iterator

from google.cloud.speech_v1p1beta1 import SpeechClient  # type: ignore
from google.cloud.speech_v1p1beta1.types import cloud_speech  # type: ignore

logger = logging.getLogger(__name__)


class GoogleClientWrapper:
    """Google Cloud Speech SDKのクライアント処理をラップ"""
    
    def __init__(self, language_code: str = "ja-JP", sample_rate: int = 16000, call_id: str = "unknown"):
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.call_id = call_id
        self._client = None
        self._init_client()
    
    def _init_client(self):
        """クライアントを初期化"""
        try:
            # 【物理的解決】環境変数をハードコーディング
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/opt/libertycall/config/google-credentials.json"
            
            self._client = SpeechClient()
            logger.info(f"[GoogleClientWrapper] Client initialized for {self.call_id}")
        except Exception as e:
            logger.error(f"[GoogleClientWrapper] Failed to initialize client: {e}", exc_info=True)
            raise
    
    def create_streaming_config(self) -> cloud_speech.StreamingRecognitionConfig:
        """ストリーミング認識設定を作成"""
        config = cloud_speech.RecognitionConfig(
            encoding=cloud_speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            language_code=self.language_code,
            enable_automatic_punctuation=True,
        )
        
        streaming_config = cloud_speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
            single_utterance=False
        )
        
        logger.warning(f"[GoogleClientWrapper] StreamingRecognitionConfig created: interim={streaming_config.interim_results}, single_utterance={streaming_config.single_utterance}")
        return streaming_config
    
    def start_streaming_recognize(self, streaming_config, request_generator) -> Iterator:
        """ストリーミング認識を開始"""
        try:
            logger.info("[GoogleClientWrapper] Starting streaming_recognize call")
            
            # 【gRPC接続の完全な可視化】streaming_recognite呼び出し前の状態を記録
            start_time = time.time()
            logger.warning(f"[GRPC_TIMING] Starting streaming_recognize at {start_time}")
            logger.warning(f"[GRPC_CONFIG] config={type(streaming_config)}")
            logger.warning(f"[GRPC_REQUEST_GEN] request_gen={type(request_generator())}")
            
            # streaming_recognize()のシグネチャ: (self, config, requests, ...)
            logger.warning(f"[ASR_STREAM_START] streaming_recognize started for call_id={self.call_id}")
            logger.warning(f"[GRPC_CALL] About to call client.streaming_recognize")
            
            # 【非同期処理のバグチェック】request_gen()が即座に実行されるか確認
            gen_start = time.time()
            gen_obj = request_generator()
            gen_elapsed = time.time() - gen_start
            logger.warning(f"[GRPC_GEN_TIMING] request_gen() took {gen_elapsed:.3f}s to create")
            
            # 実際のgRPC呼び出し
            call_start = time.time()
            os.write(2, b"[TRACE_SDK_EXEC] Calling streaming_recognize\n")
            responses = self._client.streaming_recognize(
                config=streaming_config,
                requests=gen_obj
            )
            call_elapsed = time.time() - call_start
            logger.warning(f"[GRPC_CALL_TIMING] streaming_recognize() took {call_elapsed:.3f}s to return")
            logger.info("[GoogleClientWrapper] streaming_recognize called, waiting for responses...")
            
            return responses
            
        except Exception as e:
            logger.error(f"[GoogleClientWrapper] Error in streaming_recognize: {e}", exc_info=True)
            raise
