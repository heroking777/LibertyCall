#!/usr/bin/env python3
"""ASRリクエストジェネレーターを管理"""
import os
import queue
import sys
import threading
import traceback
import logging
from typing import Iterator
from google.cloud import speech

from google.cloud.speech_v1.types import cloud_speech  # type: ignore

logger = logging.getLogger(__name__)

# グローバル変数でConfig送信を1回に制限
_config_sent_calls = set()
_config_lock = threading.Lock()


class ASRGenerator:
    """ASRリクエストジェネレーターを管理"""
    
    def __init__(self, call_id: str = "unknown"):
        self.call_id = call_id
        self.active = True
        self.requests = queue.Queue()
        # トレースログ用FD
        self.trace_fd = os.open("/tmp/gateway_google_asr.trace", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    
    def create_request_generator(self, _): # 引数のaudio_queueは無視
        """音声専用リクエストジェネレーターを作成"""
        import sys
        from google.cloud import speech
        # 内部で持っている self.requests (Queue) を使用
        sys.stderr.write(f"[DEBUG_FLOW] Generator targeting internal requests queue ID: {id(self.requests)}\n")
        sys.stderr.flush()
        
        # 最初の config yield は絶対に行わない（SDK引数と重複するため）
        while True:
            content = self.requests.get()
            # 最初のデータを即座にyieldしてGoogle側に「データがない状態での待機」をさせない
            if content:
                yield speech.StreamingRecognizeRequest(audio_content=content)
    
    def add_audio(self, data: bytes):
        """音声データをキューに追加"""
        if not getattr(self, 'active', False):
            return
        
        if data and len(data) > 0:
            sys.stderr.write(f"[TRACE_ADD_AUDIO] Putting to queue: {len(data)} bytes\n")
            sys.stderr.flush()
            self.requests.put(data)
    
    def stop(self):
        """ジェネレーターを停止"""
        self.active = False
        self.requests.put(None)  # 終了シグナル
