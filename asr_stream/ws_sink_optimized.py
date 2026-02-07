#!/usr/bin/env python3
"""
ws_sink.py - LibertyCall ASR WebSocket Server
gRPC接続を事前確立して遅延を解消するバージョン
"""

import asyncio
import websockets
import logging
from google.cloud import speech_v1 as speech
from google.api_core.client_options import ClientOptions
import grpc
import time
import threading
import queue

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================================
# グローバル設定
# ========================================
GASR_SAMPLE_RATE = 8000
WS_PORT = 9000

# ========================================
# gRPC接続オプション（重要）
# ========================================
GRPC_CHANNEL_OPTIONS = [
    # Keepalive: 30秒ごとにPINGを送信して接続維持
    ('grpc.keepalive_time_ms', 30000),
    # Keepalive timeout: 10秒以内にACKがなければ切断
    ('grpc.keepalive_timeout_ms', 10000),
    # アクティブなRPCがなくてもKeepaliveを許可
    ('grpc.keepalive_permit_without_calls', 1),
    # HTTP/2の最大PING送信数（制限なし）
    ('grpc.http2.max_pings_without_data', 0),
    # 初期ウィンドウサイズを大きく
    ('grpc.http2.initial_window_size', 1048576),  # 1MB
]

# ========================================
# SpeechClientのシングルトン管理
# ========================================
class SpeechClientManager:
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
        """シンプルなウォームアップ - クライアント初期化のみ"""
        if cls._warmed_up:
            return
        
        logger.info("=== gRPC接続ウォームアップ開始 ===")
        start = time.time()
        
        # クライアント取得（これだけでgRPCチャンネルが準備される）
        client = cls.get_client()
        
        # 実際にAPIを叩いて接続を確立
        # recognize()で短いテストを実行
        try:
            test_audio = b'\x00' * 3200  # 0.2秒の無音
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=GASR_SAMPLE_RATE,
                language_code="ja-JP",
            )
            audio = speech.RecognitionAudio(content=test_audio)
            
            # 同期recognize（短い音声なので高速）
            response = client.recognize(config=config, audio=audio)
            logger.info(f"ウォームアップ: recognize完了")
        except Exception as e:
            logger.info(f"ウォームアップ: {type(e).__name__}（接続は確立済み）")
        
        cls._warmed_up = True
        elapsed = time.time() - start
        logger.info(f"=== gRPC接続ウォームアップ完了: {elapsed:.3f}秒 ===")

# ========================================
# ASRセッション（最適化版）
# ========================================
class ASRSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.queue = queue.Queue()  # 同期キューに変更
        self.running = True
        self.first_response_logged = False
        self.session_start_time = time.time()
        self.first_audio_time = None
        self.skip_count = 50  # 最初の1秒分をスキップ
        self.chunk_count = 0
        self.interim_responded = False
        
    async def feed_audio(self, audio_data: bytes):
        """音声データをキューに追加"""
        self.chunk_count += 1
        
        if self.first_audio_time is None:
            self.first_audio_time = time.time()
            logger.info(f"[{self.session_id}] 最初の音声チャンク受信")
        
        # 最初のskip_countチャンクはスキップ
        if self.chunk_count <= self.skip_count:
            if self.chunk_count == self.skip_count:
                logger.info(f"[{self.session_id}] スキップ完了、音声送信開始")
            return
        
        self.queue.put(audio_data)  # 同期キューに追加
    
    def _request_generator(self):
        """Google ASRに送信する音声ストリームジェネレータ（元の形式）"""
        first_chunk = True
        while True:
            chunk = self.queue.get()  # 同期的に取得
            if chunk is None:
                break
            if not chunk:
                continue
            if first_chunk:
                first_chunk = False
                elapsed = time.time() - self.session_start_time
                logger.info(f"[{self.session_id}] first_chunk_yielded: {elapsed:.3f}秒")
            
            yield speech.StreamingRecognizeRequest(audio_content=chunk)
    
    async def run_recognition(self, websocket):
        """音声認識を実行"""
        logger.info(f"[{self.session_id}] 認識開始")
        
        client = SpeechClientManager.get_client()
        
        # 設定を作成
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=GASR_SAMPLE_RATE,
            language_code="ja-JP",
            enable_automatic_punctuation=True,
            model="default",
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
            single_utterance=False,
        )
        
        try:
            # streaming_recognize呼び出し（元の形式）
            call_start = time.time()
            responses = client.streaming_recognize(
                streaming_config,
                requests=self._request_generator()
            )
            call_elapsed = time.time() - call_start
            logger.info(f"[{self.session_id}] streaming_recognize呼び出し: {call_elapsed:.3f}秒")
            
            # responsesイテレータを回す
            iter_start = time.time()
            for response in responses:
                if not self.first_response_logged:
                    self.first_response_logged = True
                    iter_elapsed = time.time() - iter_start
                    total_elapsed = time.time() - self.session_start_time
                    logger.info(f"[{self.session_id}] got responses iterator: {iter_elapsed:.3f}秒 (total: {total_elapsed:.3f}秒)")
                
                for result in response.results:
                    transcript = result.alternatives[0].transcript
                    is_final = result.is_final
                    
                    logger.info(f"[{self.session_id}] {'FINAL' if is_final else 'interim'}: {transcript}")
                    
                    # 4文字以上のinterimで即座に応答（重複防止）
                    if not is_final and len(transcript) >= 4 and not self.interim_responded:
                        self.interim_responded = True
                        elapsed = time.time() - self.session_start_time
                        logger.info(f"[{self.session_id}] ★interim応答トリガー★ ({elapsed:.3f}秒)")
                        # ここで応答処理を呼び出す
                        await self.send_response(websocket, transcript, is_final=False)
                    
                    if is_final:
                        elapsed = time.time() - self.session_start_time
                        logger.info(f"[{self.session_id}] ★FINAL応答★ ({elapsed:.3f}秒)")
                        await self.send_response(websocket, transcript, is_final=True)
                        self.interim_responded = False  # リセット
                        
        except Exception as e:
            logger.error(f"[{self.session_id}] 認識エラー: {e}")
    
    async def send_response(self, websocket, transcript, is_final):
        """認識結果に応じた応答を送信"""
        # TODO: 実際の応答ロジックを実装
        logger.info(f"[{self.session_id}] 応答送信: {transcript} (final={is_final})")
    
    def stop(self):
        """セッション停止"""
        self.running = False
        self.queue.put(None)  # 同期キューに終了シグナル

# ========================================
# WebSocketハンドラ
# ========================================
async def handle_websocket(websocket, path):
    """WebSocket接続ハンドラ"""
    session_id = f"sess_{int(time.time()*1000)}"
    logger.info(f"[{session_id}] WebSocket接続開始: {path}")
    
    session = ASRSession(session_id)
    
    # 認識タスクを開始
    recognition_task = asyncio.create_task(session.run_recognition(websocket))
    
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                await session.feed_audio(message)
            else:
                logger.info(f"[{session_id}] テキストメッセージ: {message}")
    
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"[{session_id}] 接続クローズ: {e}")
    
    finally:
        session.stop()
        recognition_task.cancel()
        try:
            await recognition_task
        except asyncio.CancelledError:
            pass
        logger.info(f"[{session_id}] セッション終了")

# ========================================
# メイン
# ========================================
async def main():
    logger.info("=== LibertyCall ASR Server 起動 ===")
    
    # ★重要: サーバー起動時にgRPC接続をウォームアップ
    await SpeechClientManager.warmup()
    
    # 定期的にウォームアップを維持（オプション）
    async def periodic_warmup():
        while True:
            await asyncio.sleep(300)  # 5分ごと
            logger.info("定期ウォームアップ実行...")
            await SpeechClientManager.warmup()
    
    # バックグラウンドでウォームアップタスク開始
    asyncio.create_task(periodic_warmup())
    
    # WebSocketサーバー開始
    async with websockets.serve(handle_websocket, "0.0.0.0", WS_PORT):
        logger.info(f"WebSocket server listening on port {WS_PORT}")
        await asyncio.Future()  # 永久に待機

if __name__ == "__main__":
    asyncio.run(main())
