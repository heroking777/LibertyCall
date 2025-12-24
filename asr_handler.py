#!/usr/bin/env python3
"""
ASRハンドラー：着信制御とGoogle Streaming ASR統合

FreeSWITCHからの着信を制御し、音声案内→ASR→無反応催促→切断のフローを管理
"""
import time
import threading
import logging
from typing import Optional, Dict
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
            app: アプリケーション名（playback, speak, hangupなど）
            arg: 引数
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
        """
        着信時の処理（gateway_event_listener.pyから呼ばれる）
        """
        self.start()
    
    def start(self):
        """着信処理を開始"""
        logger.info(f"[ASRHandler] Starting call handling for {self.call_id}")
        
        # 初回アナウンス再生
        self._play_initial_prompts()
        
        # Google Streaming ASR開始
        self.asr = GoogleStreamingASR()
        self.asr.start_stream()
        
        # 無反応監視スレッド起動
        self.monitor_thread = threading.Thread(
            target=self._monitor_silence,
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info(f"[ASRHandler] Call handling started for {self.call_id}")
    
    def _play_initial_prompts(self):
        """初回アナウンス（000, 001, 002）を再生"""
        for wav_path in PROMPTS:
            if not Path(wav_path).exists():
                logger.warning(f"[ASRHandler] Audio file not found: {wav_path}")
                continue
            
            logger.info(f"[ASRHandler] Playing: {wav_path}")
            self._execute_esl_command("playback", wav_path)
            time.sleep(0.5)  # 再生完了を待つ（簡易実装）
    
    def _monitor_silence(self):
        """無反応監視と催促制御"""
        logger.info(f"[ASRHandler] Starting silence monitoring for {self.call_id}")
        
        timeout = SILENCE_TIMEOUT
        
        for reminder_idx, reminder_path in enumerate(REMINDERS, 1):
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if not self.active:
                    logger.info(f"[ASRHandler] Handler deactivated, stopping monitor")
                    return
                
                # ASR結果をチェック
                if self.asr and self.asr.has_input():
                    text = self.asr.get_text()
                    logger.info(f"[ASRHandler] ASR detected: {text}")
                    self._handle_response(text)
                    return
                
                time.sleep(0.5)  # 0.5秒間隔でチェック
            
            # タイムアウト：催促を再生
            if Path(reminder_path).exists():
                logger.info(f"[ASRHandler] Timeout {reminder_idx}, playing reminder: {reminder_path}")
                self._execute_esl_command("playback", reminder_path)
            else:
                logger.warning(f"[ASRHandler] Reminder file not found: {reminder_path}")
        
        # 全ての催促後も無反応：切断
        logger.info(f"[ASRHandler] All reminders played, no response. Hanging up {self.call_id}")
        self._execute_esl_command("hangup", "NORMAL_CLEARING")
        self.active = False
    
    def _handle_response(self, text: str):
        """
        発話検出時の処理
        
        Args:
            text: ASR認識結果テキスト
        """
        logger.info(f"[ASRHandler] Handling response: {text}")
        
        # 認識結果を復唱
        response_text = f"あなたの回答は{text}です。"
        self._execute_esl_command("speak", response_text)
        
        # 2秒待機
        time.sleep(2)
        
        # 切断
        logger.info(f"[ASRHandler] Hanging up after response: {self.call_id}")
        self._execute_esl_command("hangup", "NORMAL_CLEARING")
        self.active = False
    
    def on_audio_chunk(self, chunk: bytes):
        """
        RTP入力からASRに渡す
        
        Args:
            chunk: PCM16音声データ（16kHz）
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
        
        logger.info(f"[ASRHandler] Stopped for {self.call_id}")


# グローバルハンドラー管理
_handlers: Dict[str, ASRHandler] = {}


def get_or_create_handler(call_id: str) -> ASRHandler:
    """
    ハンドラーを取得または作成
    
    Args:
        call_id: 通話ID
        
    Returns:
        ASRHandlerインスタンス
    """
    if call_id not in _handlers:
        _handlers[call_id] = ASRHandler(call_id)
        _handlers[call_id].start()
    
    return _handlers[call_id]


def remove_handler(call_id: str):
    """
    ハンドラーを削除
    
    Args:
        call_id: 通話ID
    """
    if call_id in _handlers:
        handler = _handlers[call_id]
        handler.stop()
        del _handlers[call_id]
        logger.info(f"[ASRHandler] Removed handler for {call_id}")


def get_handler(call_id: str) -> Optional[ASRHandler]:
    """
    ハンドラーを取得（作成しない）
    
    Args:
        call_id: 通話ID
        
    Returns:
        ASRHandlerインスタンス（存在しない場合はNone）
    """
    return _handlers.get(call_id)

