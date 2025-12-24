#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASRハンドラー：着信制御とGoogle Streaming ASR統合
無反応監視と催促制御を実装
"""

import time
import threading
import logging
from typing import Optional
from pathlib import Path
from google_stream_asr import GoogleStreamingASR

logger = logging.getLogger(__name__)

# 音声ファイルパス
PROMPTS = [
    "/opt/libertycall/clients/000/audio/000_8k.wav",
    "/opt/libertycall/clients/000/audio/001_8k.wav",
    "/opt/libertycall/clients/000/audio/002_8k.wav"
]

REMINDERS = [
    "/opt/libertycall/clients/000/audio/000-004_8k.wav",
    "/opt/libertycall/clients/000/audio/000-005_8k.wav",
    "/opt/libertycall/clients/000/audio/000-006_8k.wav"
]

# タイムアウト設定（秒）
SILENCE_TIMEOUT = 10


class ASRHandler:
    """ASRハンドラー：着信制御と無反応監視"""
    
    def __init__(self, call_id: str, client_id: str = "000"):
        """
        Args:
            call_id: 通話ID
            client_id: クライアントID（デフォルト: 000）
        """
        self.call_id = call_id
        self.client_id = client_id
        self.asr: Optional[GoogleStreamingASR] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.active = True
        self.reminder_count = 0
        self.last_activity_time = time.time()
        
        logger.info(f"[ASRHandler] Initialized for call_id={call_id}, client_id={client_id}")
    
    def start_asr(self):
        """Google Streaming ASRを開始"""
        if self.asr:
            logger.warning(f"[ASRHandler] ASR already started for call_id={self.call_id}")
            return
        
        try:
            self.asr = GoogleStreamingASR(language_code="ja-JP", sample_rate=16000)
            self.asr.start_stream()
            self.last_activity_time = time.time()
            logger.info(f"[ASRHandler] ASR started for call_id={self.call_id}")
        except Exception as e:
            logger.error(f"[ASRHandler] Failed to start ASR: {e}", exc_info=True)
            self.asr = None
    
    def on_audio_chunk(self, chunk: bytes):
        """RTP入力からASRに渡す"""
        if self.asr and self.active:
            self.asr.add_audio(chunk)
            self.last_activity_time = time.time()
    
    def start_monitoring(self, gateway):
        """無反応監視スレッドを起動"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            logger.warning(f"[ASRHandler] Monitor already running for call_id={self.call_id}")
            return
        
        def monitor_silence():
            """無反応監視と催促制御"""
            logger.info(f"[ASRHandler] Monitor started for call_id={self.call_id}")
            
            # 初回アナウンス再生完了を待つ（3秒）
            time.sleep(3)
            
            # ASR開始
            self.start_asr()
            
            # 無反応監視ループ
            while self.active and self.reminder_count < len(REMINDERS):
                elapsed = time.time() - self.last_activity_time
                
                if elapsed >= SILENCE_TIMEOUT:
                    # 無反応タイムアウト
                    if self.reminder_count < len(REMINDERS):
                        reminder_path = REMINDERS[self.reminder_count]
                        if Path(reminder_path).exists():
                            logger.info(
                                f"[ASRHandler] Silence timeout ({elapsed:.1f}s), "
                                f"playing reminder {self.reminder_count + 1}: {reminder_path}"
                            )
                            try:
                                # FreeSWITCH経由で音声再生
                                gateway._handle_playback(self.call_id, reminder_path)
                                self.reminder_count += 1
                                self.last_activity_time = time.time()  # 催促再生後はリセット
                            except Exception as e:
                                logger.error(f"[ASRHandler] Failed to play reminder: {e}", exc_info=True)
                        else:
                            logger.warning(f"[ASRHandler] Reminder file not found: {reminder_path}")
                            self.reminder_count += 1
                    else:
                        # すべての催促を再生済み
                        logger.info(f"[ASRHandler] All reminders played, hanging up call_id={self.call_id}")
                        self.handle_no_response(gateway)
                        break
                
                # ASR結果をチェック
                if self.asr and self.asr.has_input():
                    text = self.asr.get_text()
                    if text:
                        logger.info(f"[ASRHandler] ASR detected: {text}")
                        self.handle_response(gateway, text)
                        break
                
                time.sleep(0.5)
            
            # 最終チェック：最後の催促後も10秒無反応なら切断
            if self.active and self.reminder_count >= len(REMINDERS):
                final_wait = time.time()
                while self.active and (time.time() - final_wait) < SILENCE_TIMEOUT:
                    if self.asr and self.asr.has_input():
                        text = self.asr.get_text()
                        if text:
                            logger.info(f"[ASRHandler] ASR detected after final reminder: {text}")
                            self.handle_response(gateway, text)
                            break
                    time.sleep(0.5)
                
                if self.active:
                    logger.info(f"[ASRHandler] Final timeout, hanging up call_id={self.call_id}")
                    self.handle_no_response(gateway)
        
        self.monitor_thread = threading.Thread(target=monitor_silence, daemon=True)
        self.monitor_thread.start()
        logger.info(f"[ASRHandler] Monitor thread started for call_id={self.call_id}")
    
    def handle_response(self, gateway, text: str):
        """発話検出時の処理：ASR結果を復唱して切断"""
        logger.info(f"[ASRHandler] Handling response: {text}")
        self.active = False
        
        try:
            # ASR結果を復唱（TTSで再生）
            reply_text = f"あなたの回答は{text}です。"
            gateway._send_tts(self.call_id, reply_text)
            
            # 2秒待機してから切断
            time.sleep(2)
            gateway._handle_hangup(self.call_id)
        except Exception as e:
            logger.error(f"[ASRHandler] Failed to handle response: {e}", exc_info=True)
            gateway._handle_hangup(self.call_id)
    
    def handle_no_response(self, gateway):
        """無反応時の処理：切断"""
        logger.info(f"[ASRHandler] No response detected, hanging up call_id={self.call_id}")
        self.active = False
        try:
            gateway._handle_hangup(self.call_id)
        except Exception as e:
            logger.error(f"[ASRHandler] Failed to hangup: {e}", exc_info=True)
    
    def stop(self):
        """ハンドラーを停止"""
        self.active = False
        if self.asr:
            self.asr.stop()
        logger.info(f"[ASRHandler] Stopped for call_id={self.call_id}")


# グローバルハンドラー管理（call_idごとに管理）
_handlers: dict[str, ASRHandler] = {}


def get_or_create_handler(call_id: str, client_id: str = "000") -> ASRHandler:
    """ハンドラーを取得または作成"""
    if call_id not in _handlers:
        _handlers[call_id] = ASRHandler(call_id, client_id)
    return _handlers[call_id]


def remove_handler(call_id: str):
    """ハンドラーを削除"""
    if call_id in _handlers:
        _handlers[call_id].stop()
        del _handlers[call_id]
        logger.info(f"[ASRHandler] Removed handler for call_id={call_id}")

