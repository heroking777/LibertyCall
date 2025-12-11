"""
WhisperLocalASR: faster-whisper を使用したローカルASR実装

GoogleASR と互換性のあるインターフェースを提供します。
"""
import logging
import queue
import threading
import time
from typing import Optional, Callable, Any
import numpy as np

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    WhisperModel = None  # type: ignore


class WhisperLocalASR:
    """
    faster-whisper を使用したローカルASR実装
    
    GoogleASR と互換性のあるインターフェースを提供します。
    """
    
    def __init__(
        self,
        model_name: str = "base",
        input_sample_rate: int = 16000,
        language: str = "ja",
        device: str = "cpu",
        compute_type: str = "int8",
        temperature: float = 0.0,
        vad_filter: bool = False,
        vad_parameters: Optional[dict] = None,
        ai_core: Optional[Any] = None,
        error_callback: Optional[Callable[[str, Exception], None]] = None,
    ):
        """
        WhisperLocalASR を初期化する
        
        :param model_name: Whisperモデル名（tiny, base, small, medium, large）
        :param input_sample_rate: 入力サンプリングレート（デフォルト: 16000）
        :param language: 言語コード（デフォルト: "ja"）
        :param device: デバイス（cpu または cuda）
        :param compute_type: 計算タイプ（int8, int8_float16, float16, float32）
        :param temperature: 温度パラメータ（デフォルト: 0.0）
        :param vad_filter: VADフィルタを使用するか（デフォルト: False）
        :param vad_parameters: VADパラメータ（未使用）
        :param ai_core: AICore への参照（on_transcript 呼び出し用）
        :param error_callback: エラーコールバック
        """
        self.logger = logging.getLogger("WhisperLocalASR")
        
        if not FASTER_WHISPER_AVAILABLE:
            raise RuntimeError(
                "faster-whisper パッケージがインストールされていません。"
                "`pip install faster-whisper` を実行してください。"
            )
        
        self.model_name = model_name
        self.input_sample_rate = input_sample_rate
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.temperature = temperature
        self.vad_filter = vad_filter
        self.ai_core = ai_core
        self._error_callback = error_callback
        
        # Whisperモデルのロード
        try:
            self.logger.info(f"WhisperLocalASR: Loading model '{model_name}' (device={device}, compute_type={compute_type})...")
            self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
            self.logger.info(f"WhisperLocalASR: モデル '{model_name}' のロードが完了しました")
        except Exception as e:
            self.logger.error(f"WhisperLocalASR: モデルのロードに失敗しました: {e}")
            raise
        
        # 音声バッファ（通話ごとに管理）
        self._audio_buffers: dict[str, bytearray] = {}
        self._buffer_lock = threading.Lock()
        
        # 認識処理用のスレッドとキュー
        self._q: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=100)
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 認識間隔（秒）
        self._recognition_interval = 1.0  # 1秒ごとに認識
        self._min_buffer_duration = 0.5  # 最低0.5秒の音声が必要
        
        # ワーカースレッドを起動
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._recognition_worker, daemon=True)
        self._worker_thread.start()
        self.logger.info("WhisperLocalASR: 認識ワーカースレッドを起動しました")
    
    def feed(self, call_id: str, pcm16k_bytes: bytes) -> None:
        """
        音声チャンクをバッファに追加する
        
        :param call_id: 通話ID
        :param pcm16k_bytes: 16kHz PCM16音声データ（bytes）
        """
        if not pcm16k_bytes or len(pcm16k_bytes) == 0:
            return
        
        with self._buffer_lock:
            if call_id not in self._audio_buffers:
                self._audio_buffers[call_id] = bytearray()
            self._audio_buffers[call_id].extend(pcm16k_bytes)
        
        # キューに投入（認識ワーカーが処理）
        try:
            self._q.put_nowait((call_id, pcm16k_bytes))
        except queue.Full:
            self.logger.warning(f"WhisperLocalASR: QUEUE_FULL (skipping chunk): call_id={call_id}")
        except Exception as e:
            self.logger.warning(f"WhisperLocalASR: QUEUE_PUT error (call_id={call_id}): {e}")
    
    def feed_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        """
        feed() のエイリアス（GoogleASR との互換性のため）
        
        :param call_id: 通話ID
        :param pcm16k_bytes: 16kHz PCM音声データ
        """
        self.feed(call_id, pcm16k_bytes)
    
    def _recognition_worker(self) -> None:
        """
        バックグラウンドで音声を認識するワーカースレッド
        """
        last_recognition_time: dict[str, float] = {}
        
        while not self._stop_event.is_set():
            try:
                # キューから音声チャンクを取得（タイムアウト付き）
                try:
                    call_id, chunk = self._q.get(timeout=0.5)
                except queue.Empty:
                    # タイムアウト時は、バッファに十分な音声があるかチェック
                    current_time = time.time()
                    with self._buffer_lock:
                        for cid, buffer in list(self._audio_buffers.items()):
                            buffer_duration = len(buffer) / (self.input_sample_rate * 2)  # 16bit = 2 bytes
                            
                            # 最後の認識から一定時間経過し、十分な音声がある場合
                            last_time = last_recognition_time.get(cid, 0)
                            if (current_time - last_time >= self._recognition_interval and 
                                buffer_duration >= self._min_buffer_duration):
                                self._process_recognition(cid)
                                last_recognition_time[cid] = current_time
                    continue
                
                # チャンクを受け取った場合、一定時間後に認識を実行
                current_time = time.time()
                last_time = last_recognition_time.get(call_id, 0)
                
                if current_time - last_time >= self._recognition_interval:
                    # バッファに十分な音声があるかチェック
                    with self._buffer_lock:
                        buffer = self._audio_buffers.get(call_id)
                        if buffer:
                            buffer_duration = len(buffer) / (self.input_sample_rate * 2)
                            if buffer_duration >= self._min_buffer_duration:
                                self._process_recognition(call_id)
                                last_recognition_time[call_id] = current_time
                
            except Exception as e:
                self.logger.error(f"WhisperLocalASR: 認識ワーカーでエラーが発生しました: {e}", exc_info=True)
                if self._error_callback:
                    try:
                        self._error_callback("unknown", e)
                    except Exception:
                        pass
    
    def _process_recognition(self, call_id: str) -> None:
        """
        バッファ内の音声を認識する
        
        :param call_id: 通話ID
        """
        with self._buffer_lock:
            buffer = self._audio_buffers.get(call_id)
            if not buffer or len(buffer) == 0:
                return
            
            # 音声データを numpy 配列に変換
            audio_array = np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
            
            # バッファをクリア（認識済みの音声は削除）
            self._audio_buffers[call_id] = bytearray()
        
        try:
            # Whisperで認識
            segments, info = self.model.transcribe(
                audio_array,
                language=self.language,
                temperature=self.temperature,
                beam_size=5,
                vad_filter=self.vad_filter,
            )
            
            # 認識結果を結合
            text = "".join([segment.text for segment in segments]).strip()
            
            if text:
                self.logger.info(f"WhisperLocalASR: ASR_WHISPER_FINAL: call_id={call_id} text='{text}'")
                
                # AICore の on_transcript を呼び出す
                if self.ai_core and hasattr(self.ai_core, 'on_transcript'):
                    try:
                        self.ai_core.on_transcript(call_id, text)
                    except Exception as e:
                        self.logger.error(f"WhisperLocalASR: on_transcript 呼び出しでエラー: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"WhisperLocalASR: 認識処理でエラーが発生しました (call_id={call_id}): {e}", exc_info=True)
            if self._error_callback:
                try:
                    self._error_callback(call_id, e)
                except Exception:
                    pass
    
    def reset_call(self, call_id: str) -> None:
        """
        通話の状態をリセットする（通話終了時など）
        
        :param call_id: 通話ID
        """
        with self._buffer_lock:
            if call_id in self._audio_buffers:
                # 残っている音声があれば最後に認識を実行
                buffer = self._audio_buffers[call_id]
                if buffer and len(buffer) > 0:
                    self._process_recognition(call_id)
                del self._audio_buffers[call_id]
        
        self.logger.debug(f"WhisperLocalASR: [{call_id}] ストリーミング状態をリセットしました")
    
    def end_stream(self, call_id: str) -> None:
        """
        reset_call() のエイリアス（GoogleASR との互換性のため）
        
        :param call_id: 通話ID
        """
        self.reset_call(call_id)
    
    def poll_result(self, call_id: str) -> Optional[tuple[str, float, float, float]]:
        """
        認識結果を取得する（互換性のため、常に None を返す）
        
        :param call_id: 通話ID
        :return: None（結果は on_transcript で処理される）
        """
        return None

