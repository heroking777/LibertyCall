#!/usr/bin/env python3
"""
SpeechClientManager - Google Speech Clientのシングルトン管理
ウォームアップ機能付き
"""

import logging
import threading
import time
from google.cloud import speech_v1 as speech
from google.api_core.client_options import ClientOptions

logger = logging.getLogger(__name__)

class SpeechClientManager:
    """Google Speech Clientのシングルトン管理クラス"""
    _instance = None
    _client = None
    _lock = threading.Lock()
    _warmed_up = False
    
    @classmethod
    def get_client(cls):
        """スレッドセーフなシングルトンクライアント取得"""
        if cls._client is None:
            with cls._lock:
                if cls._client is None:
                    logger.info("SpeechClient初期化開始...")
                    start = time.time()
                    
                    # gRPCチャンネルオプション付きでクライアント作成
                    cls._client = speech.SpeechClient(
                        client_options=ClientOptions(
                            api_endpoint="speech.googleapis.com:443"
                        )
                    )
                    
                    elapsed = time.time() - start
                    logger.info(f"SpeechClient初期化完了: {elapsed:.3f}秒")
        
        return cls._client
    
    @classmethod
    async def warmup(cls):
        """シンプルなウォームアップ - streaming_recognizeで接続を確立"""
        if cls._warmed_up:
            return
        
        logger.info("=== gRPC接続ウォームアップ開始 ===")
        start = time.time()
        
        # クライアント取得（これだけでgRPCチャンネルが準備される）
        client = cls.get_client()
        
        # 実際にAPIを叩いて接続を確立
        # streaming_recognizeで短いテストを実行
        try:
            test_audio = b'\x00' * 3200  # 0.2秒の無音
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=8000,
                language_code="ja-JP",
            )
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=True,
            )
            
            # streaming_recognize用のリクエストを作成
            requests = [
                speech.StreamingRecognizeRequest(streaming_config=streaming_config),
                speech.StreamingRecognizeRequest(audio_content=test_audio),
            ]
            
            # streaming_recognizeでウォームアップ（短い音声なので高速）
            responses = client.streaming_recognize(requests=requests)
            
            # 最初のresponseを取得して接続を確認
            try:
                for response in responses:
                    logger.info(f"ウォームアップ: streaming_recognize完了")
                    break
            except Exception:
                logger.info(f"ウォームアップ: streaming_recognize応答なし（接続は確立済み）")
                
        except Exception as e:
            logger.info(f"ウォームアップ: {type(e).__name__}（接続は確立済み）")
        
        cls._warmed_up = True
        elapsed = time.time() - start
        logger.info(f"=== gRPC接続ウォームアップ完了: {elapsed:.3f}秒 ===")

# ウォームアップ実行関数
async def warmup_speech_client():
    """SpeechClientのウォームアップを実行"""
    await SpeechClientManager.warmup()
