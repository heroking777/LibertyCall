#!/usr/bin/env python3
"""Google Cloud Speech-to-Text Streaming API ラッパー"""
import os
import queue
import sys
import threading
import time
import traceback
import logging
import inspect
import audioop
from typing import Optional

# サバイバル・インポート
try:
    import audioop
    AUDIOOP_AVAILABLE = True
    logging.info("audioop module imported successfully")
except ImportError as e:
    AUDIOOP_AVAILABLE = False
    logging.error(f"audioop import failed: {e}")

try:
    from google.cloud.speech_v1 import SpeechClient
    from google.cloud.speech_v1.types import cloud_speech
    SPEECH_AVAILABLE = True
except ImportError as e:
    SPEECH_AVAILABLE = False
    logging.error(f"Google Cloud Speech import failed: {e}")

logger = logging.getLogger(__name__)

TRACE_PATH = "/tmp/gateway_google_asr.trace"

def _force_trace(data: bytes):
    """安全にトレースログを出力"""
    try:
        fd = os.open(TRACE_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except Exception:
        pass


class GoogleStreamingASR:
    """Google Cloud Speech-to-Text Streaming API ラッパー"""
    
    def __init__(self, trace_fd=None):
        print("[DEBUG_ASR_INIT] Constructor started")
        self.trace_fd = trace_fd or os.open(TRACE_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.write(self.trace_fd, b"[ASR_INIT] Entry\n")
        
        # Initialize attributes
        self.has_input_data = False
        self._active = False
        self._result_text = ""
        self._stream_thread = None
        
        # 1. Generatorを最優先で初期化
        try:
            from gateway.asr.asr_generator import ASRGenerator
            self.asr_generator = ASRGenerator(call_id="google_stream_asr")
            os.write(self.trace_fd, b"[ASR_INIT] ASRGenerator created\n")
        except Exception as e:
            os.write(self.trace_fd, f"[ASR_INIT] ASRGenerator failed: {e}\n".encode())
            import traceback
            os.write(self.trace_fd, f"[ASR_INIT] Traceback: {traceback.format_exc()}\n".encode())
            raise
        
        # 2. ConfigとClientを初期化
        self._init_config()
        self._init_client()
        print("[DEBUG_ASR_INIT] Constructor finished")
    
    def _init_config(self):
        recognition_config = cloud_speech.RecognitionConfig(
            encoding=cloud_speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=8000,  # 8kHzに変更
            language_code="ja-JP",
        )
        
        self.streaming_config = cloud_speech.StreamingRecognitionConfig(
            config=recognition_config,
            interim_results=True
        )
    
    def _process_audio_chunk(self, chunk_mu_law):
        """μ-law 8kHz → LINEAR16 16kHz 変換"""
        try:
            # 1. まずμ-lawをそのまま録音（検証用）
            with open("/tmp/debug_original.pcm", "ab") as f:
                f.write(chunk_mu_law)
            
            # 2. μ-law (8bit) を LINEAR16 (16bit) に変換
            chunk_linear16 = audioop.ulaw2lin(chunk_mu_law, 2)
            with open("/tmp/debug_linear16.pcm", "ab") as f:
                f.write(chunk_linear16)
            
            # 3. サンプリングレート変換は一旦スキップ（8kHzのまま送信）
            # chunk_16khz, _ = audioop.ratecv(chunk_linear16, 2, 1, 8000, 16000, None)
            
            # 4. ゲインを調整（音量を2倍に増幅）
            chunk_linear16 = audioop.mul(chunk_linear16, 2, 2.0)
            
            return chunk_linear16  # 8kHzのまま返す
        except Exception as e:
            os.write(self.trace_fd, f"[AUDIO_CONV_ERROR] {e}\n".encode())
            # 変換失敗時は元データを返す
            return chunk_mu_law
    
    def _init_client(self):
        try:
            self._client = SpeechClient()
            os.write(self.trace_fd, b"[ASR_INIT] Client OK\n")
        except Exception as e:
            os.write(self.trace_fd, f"[ASR_INIT] Client Error: {e}\n".encode())
            raise
    
    def start(self, audio_queue: queue.Queue):
        """ストリーミング認識を開始"""
        os.write(self.trace_fd, b"[ASR_START] Called\n")
        
        self._active = True
        self._result_text = ""
        
        # Start a thread to transfer audio from audio_queue to generator's requests queue
        def transfer_audio():
            import sys
            sys.stderr.write("[THREAD_CHECK] transfer_thread started\n")
            sys.stderr.flush()
            os.write(self.trace_fd, b"[TRANSFER_THREAD] Starting audio transfer\n")
            while self._active:
                try:
                    chunk = audio_queue.get(timeout=0.5)
                    if chunk is None:
                        os.write(self.trace_fd, b"[TRANSFER_THREAD] Received None, stopping\n")
                        break
                    os.write(self.trace_fd, f"[TRANSFER_THREAD] Got {len(chunk)} bytes from audio_queue\n".encode())
                    # 音声変換：μ-law 8kHz → LINEAR16 16kHz
                    converted_chunk = self._process_audio_chunk(chunk)
                    os.write(self.trace_fd, f"[TRANSFER_THREAD] Converted to {len(converted_chunk)} bytes for Google\n".encode())
                    
                    # 変換済みデータを録音ファイルに書き出す
                    try:
                        with open("/tmp/debug_audio_raw.pcm", "ab") as f:
                            f.write(converted_chunk)
                    except Exception as e:
                        os.write(self.trace_fd, f"[AUDIO_FILE_ERROR] {e}\n".encode())
                    
                    self.asr_generator.add_audio(converted_chunk)
                    self.has_input_data = True
                except queue.Empty:
                    continue
                except Exception as e:
                    os.write(self.trace_fd, f"[TRANSFER_ERROR] {e}\n".encode())
                    break

        transfer_thread = threading.Thread(target=transfer_audio, daemon=True)
        transfer_thread.start()

        # ストリーミングスレッドを開始
        print(f"[DEBUG_START_METHOD] About to start thread with queue: {id(audio_queue)}")
        self._stream_thread = threading.Thread(
            target=self._stream_worker,
            args=(audio_queue,),
            daemon=True
        )
        self._stream_thread.start()
        print("[DEBUG_START_METHOD] Thread.start() returned")
        os.write(self.trace_fd, b"[ASR_START] Thread Started\n")
    
    def _stream_worker(self, audio_queue: queue.Queue):
        """ストリーミング処理ワーカー"""
        import sys
        import time
        sys.stderr.write("[CRITICAL_ENTRY] _stream_worker thread started\n")
        sys.stderr.flush()
        
        # 1. 必要なモジュールの再確認
        from google.cloud import speech
        
        # ループを追加して再接続を可能にする
        while True:
            try:
                # 2. generator インスタンス化
                requests = self.asr_generator.create_request_generator(audio_queue)
                
                print("[SYSTEM_CHECK] Initiating gRPC stream with explicit keywords")
                # config と requests をキーワード引数で明示（SDKの旧・新両方に対応）
                responses = self._client.streaming_recognize(
                    config=self.streaming_config, 
                    requests=requests
                )
                print("[SYSTEM_CHECK] Stream established. Awaiting responses.")
                
                for response in responses:
                    self._process_response(response)
                    
            except Exception as e:
                # エラーが出たらログを吐いて、少し待ってから再接続（リトライ）
                sys.stderr.write(f"[RECONNECT] Stream error: {e}. Retrying in 1s...\n")
                sys.stderr.flush()
                time.sleep(1)
    
    def _process_response(self, response):
        """レスポンス処理"""
        import sys
        sys.stdout.write(f"[DEBUG_WORKER] Received response from Google: {response}")
        sys.stdout.flush()
        
        if not self._active:
            return
            
        if response.results:
            result = response.results[0]
            if result.is_final:
                self._result_text = result.alternatives[0].transcript
                os.write(self.trace_fd, f"[ASR_RES] interim=False text={self._result_text}\n".encode())
                sys.stdout.write(f"[DEBUG_ASR_FINAL] Final transcript: {self._result_text}\n")
                sys.stdout.flush()
            elif result.alternatives:
                interim_text = result.alternatives[0].transcript
                os.write(self.trace_fd, f"[ASR_RES] interim=True text={interim_text}\n".encode())
                sys.stdout.write(f"[DEBUG_ASR_INTERIM] Interim transcript: {interim_text}\n")
                sys.stdout.flush()
        else:
            sys.stdout.write("[DEBUG_ASR_RESPONSE] No results in response\n")
            sys.stdout.flush()
    
    def start_stream(self):
        """Legacy method - use start() instead"""
        if not hasattr(self, '_buff') or self._buff is None:
            self._buff = queue.Queue()
        self.start(self._buff)
    
    def stop(self):
        """ストリーミングを停止"""
        self._active = False
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2.0)
    
    def get_result(self) -> str:
        """認識結果を取得"""
        return self._result_text or ""
    
    def get_text(self) -> str:
        """認識結果を取得（別名）"""
        return self.get_result()
    
    def has_input(self) -> bool:
        """入力データがあるかチェック"""
        return self.has_input_data
