#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASRハンドラー：着信制御とGoogle Streaming ASR統合

着信 → 音声ファイル再生 → ASR開始 → 無反応監視 → 催促 → 切断
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
SILENCE_TIMEOUT = 10.0


class ASRHandler:
    """ASRハンドラー：着信制御とASR統合"""
    
    def __init__(self, call_id: str):
        """
        初期化
        
        Args:
            call_id: 通話ID
        """
        self.call_id = call_id
        self.asr: Optional[GoogleStreamingASR] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.active = True
        self.esl_connection = None
        self._init_esl_connection()
        
        logger.info(f"[ASRHandler] Initialized for call_id={call_id}")
    
    def _init_esl_connection(self):
        """FreeSWITCH ESL接続を初期化"""
        try:
            from libs.esl.ESL import ESLconnection
            
            esl_host = "127.0.0.1"
            esl_port = 8021
            esl_password = "ClueCon"
            
            self.esl_connection = ESLconnection(esl_host, esl_port, esl_password)
            
            if not self.esl_connection.connected():
                logger.error("[ASRHandler] Failed to connect to FreeSWITCH ESL")
                self.esl_connection = None
        except ImportError:
            logger.warning("[ASRHandler] ESL module not available")
            self.esl_connection = None
        except Exception as e:
            logger.error(f"[ASRHandler] Failed to initialize ESL: {e}")
            self.esl_connection = None
    
    def _execute_esl_command(self, app: str, arg: str = ""):
        """
        FreeSWITCH ESLコマンドを実行
        
        Args:
            app: アプリケーション名（例: "playback", "hangup"）
            arg: 引数（例: ファイルパス）
        """
        if not self.esl_connection or not self.esl_connection.connected():
            logger.warning(f"[ASRHandler] ESL not connected, cannot execute: {app} {arg}")
            return False
        
        try:
            # execute()メソッドを使用（非同期実行）
            result = self.esl_connection.execute(app, arg, uuid=self.call_id, force_async=True)
            logger.info(f"[ASRHandler] Executed: {app} {arg} (call_id={self.call_id})")
            return True
        except Exception as e:
            logger.error(f"[ASRHandler] Failed to execute {app} {arg}: {e}")
            return False
    
    def on_incoming_call(self):
        """着信時の処理：ASR開始と無反応監視
        
        注意: 音声ファイル（000〜002）の再生はFreeSWITCHのdialplanで既に実行されているため、
        ここではASRの開始と監視のみを行う。
        """
        logger.info(f"[ASRHandler] Processing incoming call: {self.call_id}")
        
        # Google Streaming ASR開始
        # 注意: 000〜002の再生はFreeSWITCHのdialplanで実行されるため、
        # 再生完了を待たずにASRを開始する（ストリーミングモードのため）
        self.asr = GoogleStreamingASR(language_code="ja-JP", sample_rate=16000)
        self.asr.start_stream()
        
        logger.info("[ASRHandler] Google Streaming ASR started")
        
        # 無反応監視スレッド起動
        # 000〜002の再生完了後（約10秒後）から監視を開始
        time.sleep(10)  # 初回アナウンス再生完了を待つ
        
        self.monitor_thread = threading.Thread(
            target=self._monitor_silence,
            daemon=True
        )
        self.monitor_thread.start()
    
    def _monitor_silence(self):
        """無反応監視と催促制御"""
        logger.info("[ASRHandler] Silence monitoring started")
        
        timeout = SILENCE_TIMEOUT
        
        for reminder_idx, reminder_path in enumerate(REMINDERS, 1):
            if not self.active:
                break
            
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if not self.active:
                    return
                
                if self.asr and self.asr.has_input():
                    text = self.asr.get_text()
                    if text:
                        self._handle_response(text)
                        return
                
                time.sleep(0.5)
            
            # タイムアウト：催促を再生
            if Path(reminder_path).exists():
                logger.info(f"[ASRHandler] Playing reminder {reminder_idx}: {reminder_path}")
                self._execute_esl_command("playback", reminder_path)
            else:
                logger.warning(f"[ASRHandler] Reminder file not found: {reminder_path}")
        
        # すべての催促を再生しても無反応：切断
        logger.info("[ASRHandler] No response after all reminders, hanging up")
        self._execute_esl_command("hangup", "NORMAL_CLEARING")
        self.active = False
    
    def _handle_response(self, text: str):
        """
        発話検出時の処理
        
        Args:
            text: ASR認識結果テキスト
        """
        logger.info(f"[ASRHandler] Response detected: {text}")
        
        # 復唱（TTS）
        reply_text = f"あなたの回答は{text}です。"
        logger.info(f"[ASRHandler] Replying: {reply_text}")
        
        # TTS再生（Google TTSを使用する場合は、音声ファイルを生成して再生）
        # 簡易版：speakアプリケーションを使用（fliteが利用可能な場合）
        # 実際の実装では、TTSエンジンを使用して音声ファイルを生成・再生する
        try:
            self._execute_esl_command("speak", f"flite|kal|{reply_text}")
            time.sleep(3)  # TTS再生完了を待つ
        except Exception as e:
            logger.warning(f"[ASRHandler] TTS playback failed: {e}, proceeding to hangup")
        
        # 切断
        logger.info("[ASRHandler] Hanging up after response")
        self._execute_esl_command("hangup", "NORMAL_CLEARING")
        self.active = False
    
    def on_audio_chunk(self, chunk: bytes):
        """
        RTP入力からASRに音声データを渡す
        
        Args:
            chunk: PCM16形式の音声データ（16kHz, 16bit, モノラル）
        """
        if self.asr and self.active:
            self.asr.add_audio(chunk)
    
    def stop(self):
        """ハンドラーを停止"""
        self.active = False
        
        if self.asr:
            self.asr.stop()
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        
        logger.info(f"[ASRHandler] Stopped for call_id={self.call_id}")


# グローバルインスタンス管理（call_idごと）
_handlers: dict[str, ASRHandler] = {}


def get_or_create_handler(call_id: str) -> ASRHandler:
    """
    ハンドラーを取得または作成
    
    Args:
        call_id: 通話ID
        
    Returns:
        ASRHandler: ハンドラーインスタンス
    """
    if call_id not in _handlers:
        _handlers[call_id] = ASRHandler(call_id)
    return _handlers[call_id]


def remove_handler(call_id: str):
    """
    ハンドラーを削除
    
    Args:
        call_id: 通話ID
    """
    if call_id in _handlers:
        _handlers[call_id].stop()
        del _handlers[call_id]
        logger.info(f"[ASRHandler] Removed handler for call_id={call_id}")

