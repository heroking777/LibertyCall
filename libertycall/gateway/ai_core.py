import logging
import numpy as np
import os
import wave
import time
import threading
import queue
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any, Callable
from dataclasses import dataclass
try:
    from google.cloud import texttospeech  # type: ignore
    from google.auth.exceptions import DefaultCredentialsError  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    texttospeech = None

    class DefaultCredentialsError(Exception):
        """Fallback exception when google-auth is unavailable."""

from .intent_rules import (
    classify_intent,
    get_response_template,
    get_template_config,
    normalize_text,
    select_template_ids,
)

# WhisperLocalASR は whisper プロバイダ使用時のみインポート（google 使用時は絶対にインポートしない）

try:
    from google.cloud.speech_v1p1beta1 import SpeechClient  # type: ignore
    from google.cloud.speech_v1p1beta1.types import cloud_speech  # type: ignore
    GOOGLE_SPEECH_AVAILABLE = True
except ImportError:
    GOOGLE_SPEECH_AVAILABLE = False
    SpeechClient = None
    cloud_speech = None

# 定数定義
MIN_TEXT_LENGTH_FOR_INTENT = 2  # 「はい」「うん」も判定可能に
PRE_STREAM_BUFFER_DURATION_SEC = 0.3
DEBUG_RECORDING_DURATION_SEC = 5.0


class GoogleASR:
    """
    Google Cloud Speech-to-Text v1p1beta1 を使用したストリーミングASR実装
    
    要件:
    - StreamingRecognize (v1p1beta1) を使用
    - ローカルVADは無効（Google内部のVADに完全依存）
    - 通話ごとに StreamingRecognize を開始し、常時接続を維持
    - RTP 20ms フレームを feed() でそのまま Google に送る
    - 16kHz / PCM16 / mono（変換不要）
    - model はデフォルトの enhanced model を使用（ja-JP では universal_speech_model はサポートされていない）
    """
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        language_code: str = "ja-JP",
        sample_rate: int = 16000,
        phrase_hints: Optional[List[str]] = None,
        ai_core: Optional[Any] = None,
        error_callback: Optional[Callable[[str, Exception], None]] = None,
    ):
        """
        GoogleASR を初期化する
        
        :param project_id: Google Cloud プロジェクトID（環境変数 LC_GOOGLE_PROJECT_ID から取得可能）
        :param credentials_path: 認証情報ファイルのパス（環境変数 LC_GOOGLE_CREDENTIALS_PATH から取得可能）
        :param language_code: 言語コード（デフォルト: "ja-JP"）
        :param sample_rate: サンプリングレート（デフォルト: 16000、変換不要）
        :param phrase_hints: フレーズヒントのリスト
        """
        self.logger = logging.getLogger("GoogleASR")
        
        if not GOOGLE_SPEECH_AVAILABLE:
            raise RuntimeError(
                "google-cloud-speech パッケージがインストールされていません。"
                "`pip install google-cloud-speech` を実行してください。"
            )
        
        # 環境変数から設定を取得
        self.project_id = project_id or os.getenv("LC_GOOGLE_PROJECT_ID") or "libertycall-main"
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.phrase_hints = phrase_hints or []
        self.ai_core = ai_core  # AICore への参照（on_transcript 呼び出し用）
        self._error_callback = error_callback  # エラーコールバック（ASR エラー時に呼ばれる）
        
        # プロジェクトIDが未設定の場合はデフォルトを使用（認証ファイルから読み取ることも可能）
        if not self.project_id:
            self.logger.warning(
                "LC_GOOGLE_PROJECT_ID が未設定です。デフォルト値 'libertycall-main' を使用します。"
            )
            self.project_id = "libertycall-main"
        
        # 認証ファイルパスの決定:
        # 優先順位: 
        #   1) GOOGLE_APPLICATION_CREDENTIALS
        #   2) LC_GOOGLE_CREDENTIALS_PATH
        #   3) __init__ 引数 credentials_path
        #   4) プロジェクト標準の key パス
        cand_paths: List[str] = []

        env_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if env_creds:
            cand_paths.append(env_creds)

        env_lc_creds = os.getenv("LC_GOOGLE_CREDENTIALS_PATH")
        if env_lc_creds and env_lc_creds not in cand_paths:
            cand_paths.append(env_lc_creds)

        if credentials_path:
            cand_paths.append(credentials_path)

        # デフォルト候補（存在するものだけが実際に使われる）
        cand_paths.extend(
            [
                "/opt/libertycall/key/google_tts.json",
                "/opt/libertycall/key/libertycall-main-7e4af202cdff.json",
            ]
        )

        self.credentials_path = None
        for p in cand_paths:
            if p and os.path.exists(p):
                self.credentials_path = p
                break

        if self.credentials_path:
            self.logger.info(f"GoogleASR: using credentials file: {self.credentials_path}")
        else:
            self.logger.error(
                "GoogleASR: no valid credentials file found. "
                "Set GOOGLE_APPLICATION_CREDENTIALS or LC_GOOGLE_CREDENTIALS_PATH "
                "to a valid service-account JSON."
            )
        
        # 認証情報を環境変数に設定
        if self.credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
        
        # SpeechClient の初期化
        try:
            self.client = SpeechClient()  # type: ignore[call-overload]
            self.logger.info(
                f"GoogleASR: 初期化完了 (project_id={self.project_id}, language={self.language_code}, "
                f"model=default_enhanced, interim_results=True)"
            )
        except Exception as e:
            error_msg = str(e)
            if "credentials" in error_msg.lower() or "was not found" in error_msg:
                self.logger.error(
                    f"GoogleASR: 初期化失敗（認証エラー）: {error_msg}\n"
                    f"認証ファイルのパス: {self.credentials_path or 'GOOGLE_APPLICATION_CREDENTIALS 環境変数を確認'}\n"
                    f"プロジェクトID: {self.project_id}"
                )
            else:
                self.logger.error(f"GoogleASR: 初期化失敗: {error_msg}")
            raise
        
        # シンプルなストリーム管理：state 最小限
        # 【修正】キューサイズを200→500に増加（頭切れ防止）
        self._q: queue.Queue[bytes] = queue.Queue(maxsize=500)
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 【修正】ストリーム起動前の音声をバッファリング（最初の100〜300msを保持）
        self._pre_stream_buffer: bytearray = bytearray()
        self._pre_stream_buffer_max_bytes = int(16000 * 2 * PRE_STREAM_BUFFER_DURATION_SEC)  # 16kHz * 16bit(2byte) * duration
        
        # デバッグ用：Google に送る生 PCM を一時的に貯める（最大 5 秒）
        self._debug_raw = bytearray()
        self._debug_max_bytes = int(16000 * 2 * DEBUG_RECORDING_DURATION_SEC)  # 16kHz * 16bit(2byte) * duration
    
    def _start_stream_worker(self, call_id: str) -> None:
        """
        ストリームワーカースレッドを起動する（スレッドが死んでたら再起動）
        
        :param call_id: 通話ID（on_transcript 呼び出し用）
        """
        # 【修正理由】既存スレッドが生きている場合でも call_id を更新する必要がある
        # TEMP_CALL のままになると、on_transcript で正しい call_id が使われない
        self._current_call_id = call_id  # call_id を常に更新（on_transcript 呼び出し用）
        
        # もし self._stream_thread is not None かつ self._stream_thread.is_alive() なら return
        if self._stream_thread is not None and self._stream_thread.is_alive():
            self.logger.debug(f"GoogleASR: STREAM_WORKER_ALREADY_RUNNING call_id={call_id}")
            # 【修正】ストリームが既に起動している場合、バッファがあれば送信
            if len(self._pre_stream_buffer) > 0:
                self._flush_pre_stream_buffer()
            return
        
        # それ以外なら新しいスレッドを起動
        self._stop_event.clear()
        self._stream_thread = threading.Thread(
            target=self._stream_worker,
            daemon=True
        )
        self._stream_thread.start()
        self.logger.info(f"GoogleASR: STREAM_WORKER_START call_id={call_id}")
        
        # ChatGPT音声風: 通話開始時に200ms無音フレームを送信してウォームアップ
        # 16kHz * 2バイト * 0.2秒 = 6400バイト
        warmup_silence = b"\x00" * 6400
        try:
            self._q.put_nowait(warmup_silence)
            self.logger.debug(f"GoogleASR: WARMUP_SILENCE sent: {len(warmup_silence)} bytes (200ms)")
        except queue.Full:
            self.logger.warning("GoogleASR: WARMUP_SILENCE queue full, skipping")
        
        # 【修正】ストリーム起動後、バッファがあれば送信
        if len(self._pre_stream_buffer) > 0:
            self._flush_pre_stream_buffer()
    
    def _stream_worker(self) -> None:
        """
        Google StreamingRecognize をバックグラウンドで回すワーカー。
        """
        self.logger.debug("GoogleASR._stream_worker: start")
        
        def request_generator_from_queue():
            """
            audio_queue に積まれた PCM を Google の StreamingRecognizeRequest に変換するジェネレータ。
            Asterisk 側は 20ms ごとに RTP を送ってくるが、ここで明示的に sleep する必要はない。
            ジェネレータなので、yield で制御が呼び元に戻るため sleep 不要。
            """
            empty_count = 0  # 【修正】連続して空の回数をカウント
            while not self._stop_event.is_set():
                try:
                    # 【修正】timeout を 0.1 秒に短縮（より頻繁にチェック）
                    # 音声が来ない場合でも定期的に空のチャンクを送ってタイムアウトを防ぐ
                    chunk = self._q.get(timeout=0.1)
                    empty_count = 0  # 音声が来たらリセット
                except queue.Empty:
                    if self._stop_event.is_set():
                        break
                    empty_count += 1
                    # 【修正】10回連続で空の場合（約1秒）、空のチャンクを送ってタイムアウトを防ぐ
                    # Google側は音声が来ないとタイムアウトするため、定期的に空のチャンクを送る
                    if empty_count >= 10:
                        empty_count = 0
                        # 空のチャンクを送る（Google側のタイムアウトを防ぐ）
                        yield cloud_speech.StreamingRecognizeRequest(audio_content=b"")  # type: ignore[union-attr]
                    continue
                
                if chunk is None:
                    # sentinel → ストリーム終了
                    self.logger.debug("GoogleASR.request_generator_from_queue: got sentinel, exiting")
                    break
                
                # bytes でない場合はスキップ
                if not isinstance(chunk, bytes) or len(chunk) == 0:
                    continue
                
                # ここで1リクエスト分を yield して制御が呼び元に戻るので、
                # 追加の sleep は不要
                yield cloud_speech.StreamingRecognizeRequest(audio_content=chunk)  # type: ignore[union-attr]
        
        try:
            
            # 2. streaming 用 config を作成
            # RecognitionConfig を作成
            # 注意: universal_speech_model は ja-JP ではサポートされていないため、
            # デフォルトモデルを使用（model パラメータを削除）
            # language_code は self.language_code を使用（初期化時に "ja" が設定されている）
            config = cloud_speech.RecognitionConfig(  # type: ignore[union-attr]
                encoding=cloud_speech.RecognitionConfig.AudioEncoding.LINEAR16,  # type: ignore[union-attr]
                sample_rate_hertz=16000,
                language_code=self.language_code,  # "ja" が設定されている（初期化時に "ja" を指定）
                use_enhanced=True,  # Enhanced model を使用（ja-JP で利用可能な enhanced model）
                # model="universal_speech_model",  # ja-JP ではサポートされていないため削除
                audio_channel_count=1,
                enable_separate_recognition_per_channel=False,
                enable_automatic_punctuation=True,
                max_alternatives=1,
                speech_contexts=[
                    cloud_speech.SpeechContext(  # type: ignore[union-attr]
                        phrases=["もしもし", "こんにちは", "ありがとうございます", "お願いします", "失礼します", "担当者", "たんとうしゃ", "担当の者", "オペレーター"],
                    )
                ],
            )
            
            # ユーザー指定の phrase_hints がある場合は追加
            if self.phrase_hints:
                if config.speech_contexts and len(config.speech_contexts) > 0:
                    existing_phrases = list(config.speech_contexts[0].phrases) if config.speech_contexts[0].phrases else []
                    config.speech_contexts[0].phrases = existing_phrases + self.phrase_hints
                else:
                    config.speech_contexts = [
                        cloud_speech.SpeechContext(phrases=self.phrase_hints)  # type: ignore[union-attr]
                    ]
            
            # StreamingRecognitionConfig を作成
            streaming_config = cloud_speech.StreamingRecognitionConfig(  # type: ignore[union-attr]
                config=config,
                interim_results=True,
                single_utterance=False,
            )
            
            # 3. streaming_recognize を呼ぶ
            self.logger.info(
                "GoogleASR: STREAM_WORKER_LOOP_START (model=default_enhanced, "
                f"interim_results=True, language={config.language_code})"
            )
            responses = self.client.streaming_recognize(
                config=streaming_config,
                requests=request_generator_from_queue(),
            )
            
            for response in responses:
                # レスポンス全体をログに出す
                self.logger.info("GoogleASR: STREAM_RESPONSE: %s", response)
                
                # response.results を回して、is_final / alternatives[0].transcript / confidence を取り出す
                for result in response.results:
                    if not result.alternatives:
                        continue
                    
                    alt = result.alternatives[0]
                    transcript = alt.transcript
                    is_final = result.is_final
                    confidence = alt.confidence if hasattr(alt, 'confidence') and alt.confidence else 0.0
                    
                    # 【追加】ASR の詳細ログ（DEBUGレベルに変更）
                    self.logger.debug(
                        "[ASR_DEBUG] google_raw call_id=%s is_final=%s transcript=%r confidence=%s",
                        getattr(self, "_current_call_id", None) or "TEMP_CALL",
                        is_final,
                        transcript,
                        confidence if confidence else None,
                    )
                    
                    self.logger.info(
                        "GoogleASR: ASR_GOOGLE_RAW: final=%s conf=%.3f text=%s",
                        is_final, confidence, transcript,
                    )
                    
                    # 【修正】partial（is_final=False）も on_transcript に送る
                    if self.ai_core:
                        try:
                            # call_id を取得（feed_audio で渡された call_id を使用）
                            call_id = getattr(self, '_current_call_id', 'TEMP_CALL')
                            
                            # ChatGPT音声風: partial結果を受信した瞬間に即反応（バックチャネル）
                            if not is_final:
                                text_stripped = transcript.strip() if transcript else ""
                                if 1 <= len(text_stripped) <= 6:
                                    backchannel_keywords = ["はい", "えっと", "あの", "ええ", "そう", "うん", "ああ"]
                                    if any(keyword in text_stripped for keyword in backchannel_keywords):
                                        self.logger.debug(f"[BACKCHANNEL_TRIGGER_ASR] Detected short utterance: {text_stripped}")
                                        # tts_callback が設定されている場合のみ実行（非同期で実行）
                                        if hasattr(self.ai_core, 'tts_callback') and self.ai_core.tts_callback:  # type: ignore[attr-defined]
                                            try:
                                                # 非同期タスクで実行（ブロックしない）
                                                import asyncio
                                                try:
                                                    loop = asyncio.get_event_loop()
                                                    loop.create_task(
                                                        asyncio.to_thread(
                                                            self.ai_core.tts_callback,  # type: ignore[misc, attr-defined]
                                                            call_id, "はい", None, False
                                                        )
                                                    )
                                                except RuntimeError:
                                                    # イベントループが実行されていない場合は同期実行
                                                    self.ai_core.tts_callback(call_id, "はい", None, False)  # type: ignore[misc, attr-defined]
                                                self.logger.info(f"[BACKCHANNEL_SENT_ASR] call_id={call_id} text='はい' (triggered by partial: {text_stripped!r})")
                                            except Exception as e:
                                                self.logger.exception(f"[BACKCHANNEL_ERROR_ASR] call_id={call_id} error={e}")
                            
                            # partial と final の両方を on_transcript に送る
                            self.ai_core.on_transcript(call_id, transcript, is_final=is_final)
                        except Exception as e:
                            self.logger.exception(f"GoogleASR: on_transcript 呼び出しエラー: {e}")
                    
                    # final の場合は追加のログを出力
                    if is_final:
                        self.logger.info(
                            "GoogleASR: ASR_GOOGLE_FINAL: conf=%.3f text=%s",
                            confidence, transcript,
                        )
        except Exception as e:
            # まずログ
            self.logger.exception("GoogleASR._stream_worker: unexpected error: %s", e)
            self.logger.info("ASR_GOOGLE_ERROR: %s", e)
            self.logger.warning("GoogleASR: STREAM_WORKER_CRASHED (will restart on next feed_audio)")
            # 可能なら、現在の call_id に対してエラーハンドラを通知する
            call_id = getattr(self, "_current_call_id", None) or "TEMP_CALL"
            if self._error_callback is not None:
                try:
                    self._error_callback(call_id, e)
                except Exception as cb_err:
                    self.logger.exception(
                        "GoogleASR._stream_worker: error_callback failed: %s", cb_err
                    )
        finally:
            # スレッドハンドルを None に戻す（次回 feed_audio で再起動可能にする）
            self._stream_thread = None
            
            # STREAM_WORKER_END を INFO で出す
            self.logger.debug("GoogleASR._stream_worker: stop")
            
            # _debug_raw を /tmp/google_chunk.raw に保存（エラー時も必ず保存）
            try:
                if self._debug_raw:
                    debug_path = "/tmp/google_chunk.raw"
                    with open(debug_path, "wb") as f:
                        f.write(self._debug_raw)
                    self.logger.info(
                        f"GoogleASR: DEBUG_RAW_DUMP: path={debug_path} bytes={len(self._debug_raw)}"
                    )
            except Exception as e:
                self.logger.exception(f"GoogleASR: DEBUG_RAW_DUMP_FAILED: {e}")
    
    def _flush_pre_stream_buffer(self) -> None:
        """
        ストリーム起動前のバッファをキューに送信する
        """
        if len(self._pre_stream_buffer) == 0:
            return
        
        buffer_copy = bytes(self._pre_stream_buffer)
        self._pre_stream_buffer.clear()
        
        try:
            self._q.put_nowait(buffer_copy)
            self.logger.info(
                "GoogleASR: PRE_STREAM_BUFFER_FLUSHED: len=%d bytes",
                len(buffer_copy)
            )
        except queue.Full:
            self.logger.warning(
                "GoogleASR: PRE_STREAM_BUFFER_FLUSH_FAILED (queue full): len=%d bytes",
                len(buffer_copy)
            )
        except Exception as e:
            self.logger.warning(
                f"GoogleASR: PRE_STREAM_BUFFER_FLUSH_ERROR: {e}"
            )
    
    def feed_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        """
        ストリーミングモード: 音声チャンクをキューに投入する
        
        :param call_id: 通話ID（ログ用のみ）
        :param pcm16k_bytes: 16kHz PCM16音声データ（bytes、変換不要）
        """
        if not pcm16k_bytes or len(pcm16k_bytes) == 0:
            return
        
        # 【修正】ストリームが起動しているかチェック
        stream_running = (self._stream_thread is not None and self._stream_thread.is_alive())
        
        # ストリームが起動していない場合、バッファリング
        if not stream_running:
            # バッファサイズ制限内なら追加
            if len(self._pre_stream_buffer) < self._pre_stream_buffer_max_bytes:
                self._pre_stream_buffer.extend(pcm16k_bytes)
                self.logger.debug(
                    "GoogleASR: PRE_STREAM_BUFFER: call_id=%s len=%d bytes (total=%d)",
                    call_id, len(pcm16k_bytes), len(self._pre_stream_buffer)
                )
            else:
                # バッファが満杯の場合は、ストリームを強制起動
                self.logger.warning(
                    "GoogleASR: PRE_STREAM_BUFFER_FULL: forcing stream start (call_id=%s)",
                    call_id
                )
                self._start_stream_worker(call_id)
                # バッファをフラッシュしてから現在のチャンクを送信
                self._flush_pre_stream_buffer()
                stream_running = True
        
        # ストリームを起動（既に起動している場合は何もしない）
        if not stream_running:
            self._start_stream_worker(call_id)
        
        # デバッグ用：最初の数秒だけ生 PCM を貯める
        if len(self._debug_raw) < self._debug_max_bytes:
            remain = self._debug_max_bytes - len(self._debug_raw)
            self._debug_raw.extend(pcm16k_bytes[:remain])
        
        # 【修正】queue.put を put_nowait に変更（ノンブロッキング化）
        try:
            self._q.put_nowait(pcm16k_bytes)
            self.logger.info(
                "GoogleASR: QUEUE_PUT: call_id=%s len=%d bytes",
                call_id, len(pcm16k_bytes)
            )
        except queue.Full:
            # キューが満杯の場合は警告してスキップ（音声ロスを最小化）
            self.logger.warning(
                f"GoogleASR: QUEUE_FULL (skipping chunk): call_id={call_id} len={len(pcm16k_bytes)} bytes"
            )
        except Exception as e:
            self.logger.warning(
                f"GoogleASR: QUEUE_PUT error (call_id={call_id}): {e}"
            )
    
    def poll_result(self, call_id: str) -> Optional[Tuple[str, float, float, float]]:
        """
        ストリーミングモード: 確定した発話があればテキストを返す
        （単一ストリーム版では未実装、常に None を返す）
        
        :param call_id: 通話ID（互換性のため残す）
        :return: None（結果は ASR_GOOGLE_FINAL ログで確認）
        """
        # 単一ストリーム版では結果キューを持たないため、常に None を返す
        # 結果は ASR_GOOGLE_FINAL ログで確認可能
        return None
    
    def end_stream(self, call_id: str) -> None:
        """
        ストリーミング認識を終了する（通話終了時に呼び出される）
        
        :param call_id: 通話ID（ログ用のみ）
        """
        # self._stop_event.set()
        self._stop_event.set()
        
        # 【修正】バッファがあれば先に送信
        if len(self._pre_stream_buffer) > 0:
            self._flush_pre_stream_buffer()
        
        # self._q.put(None)（request_generator に「終了」を知らせるための sentinel）
        try:
            self._q.put_nowait(None)  # type: ignore[arg-type]
        except queue.Full:
            # キューが満杯の場合は警告
            self.logger.warning("GoogleASR: QUEUE_FULL when sending sentinel")
        except Exception:
            pass
        
        # スレッドの終了を待つ
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=2.0)
            self._stream_thread = None
        
        # デバッグ用 raw をクリア
        self._debug_raw = bytearray()
        
        # 【修正】バッファもクリア
        self._pre_stream_buffer.clear()
    
    def feed(self, call_id: str, pcm16k_bytes: bytes) -> None:
        """
        WhisperLocalASR との互換性のためのエイリアス
        
        :param call_id: 通話ID
        :param pcm16k_bytes: 16kHz PCM音声データ
        """
        self.feed_audio(call_id, pcm16k_bytes)
    
    def reset_call(self, call_id: str) -> None:
        """
        ストリーミングモード: call_idの状態をリセット（通話終了時など）
        
        :param call_id: 通話ID（ログ用のみ）
        """
        self.end_stream(call_id)
        self.logger.debug(f"[{call_id}] GoogleASR ストリーミング状態をリセット")


class ConversationState:
    """
    AICore の session_states[call_id] をラップする薄い状態オブジェクト。
    
    内部に raw dict を持ちつつ、よく使うフィールドにはプロパティでアクセスする。
    実際の保存形式は従来通り dict のまま（後方互換のため）。
    今は AICore 内部でのみ使用。
    """
    
    def __init__(self, raw: Dict[str, Any]) -> None:
        self.raw = raw
    
    @property
    def phase(self) -> str:
        return self.raw.get("phase", "ENTRY")
    
    @phase.setter
    def phase(self, value: str) -> None:
        self.raw["phase"] = value
    
    @property
    def last_intent(self) -> Optional[str]:
        return self.raw.get("last_intent")
    
    @last_intent.setter
    def last_intent(self, value: Optional[str]) -> None:
        self.raw["last_intent"] = value
    
    @property
    def handoff_state(self) -> str:
        return self.raw.get("handoff_state", "idle")
    
    @handoff_state.setter
    def handoff_state(self, value: str) -> None:
        self.raw["handoff_state"] = value
    
    @property
    def handoff_retry_count(self) -> int:
        return int(self.raw.get("handoff_retry_count", 0))
    
    @handoff_retry_count.setter
    def handoff_retry_count(self, value: int) -> None:
        self.raw["handoff_retry_count"] = int(value)
    
    @property
    def transfer_requested(self) -> bool:
        return bool(self.raw.get("transfer_requested", False))
    
    @transfer_requested.setter
    def transfer_requested(self, value: bool) -> None:
        self.raw["transfer_requested"] = bool(value)
    
    @property
    def transfer_executed(self) -> bool:
        return bool(self.raw.get("transfer_executed", False))
    
    @transfer_executed.setter
    def transfer_executed(self, value: bool) -> None:
        self.raw["transfer_executed"] = bool(value)
    
    @property
    def unclear_streak(self) -> int:
        return int(self.raw.get("unclear_streak", 0))
    
    @unclear_streak.setter
    def unclear_streak(self, value: int) -> None:
        self.raw["unclear_streak"] = int(value)
    
    @property
    def not_heard_streak(self) -> int:
        return int(self.raw.get("not_heard_streak", 0))
    
    @not_heard_streak.setter
    def not_heard_streak(self, value: int) -> None:
        self.raw["not_heard_streak"] = int(value)
    
    @property
    def handoff_completed(self) -> bool:
        return bool(self.raw.get("handoff_completed", False))
    
    @handoff_completed.setter
    def handoff_completed(self, value: bool) -> None:
        self.raw["handoff_completed"] = bool(value)
    
    @property
    def handoff_prompt_sent(self) -> bool:
        return bool(self.raw.get("handoff_prompt_sent", False))
    
    @handoff_prompt_sent.setter
    def handoff_prompt_sent(self, value: bool) -> None:
        self.raw["handoff_prompt_sent"] = bool(value)
    
    @property
    def meta(self) -> Dict[str, Any]:
        m = self.raw.get("meta")
        if not isinstance(m, dict):
            m = {}
            self.raw["meta"] = m
        return m
    
    @meta.setter
    def meta(self, value: Dict[str, Any]) -> None:
        self.raw["meta"] = value
    
    @property
    def last_ai_templates(self) -> List[str]:
        templates = self.raw.get("last_ai_templates")
        if not isinstance(templates, list):
            templates = []
            self.raw["last_ai_templates"] = templates
        return templates
    
    @last_ai_templates.setter
    def last_ai_templates(self, value: List[str]) -> None:
        self.raw["last_ai_templates"] = value

    @property
    def no_input_streak(self) -> int:
        return int(self.raw.get("no_input_streak", 0))
    
    @no_input_streak.setter
    def no_input_streak(self, value: int) -> None:
        self.raw["no_input_streak"] = int(value)


class MisunderstandingGuard:
    """
    unclear_streak / not_heard_streak に基づいて、
    - 110（わからない系）を出すか
    - 0604（ハンドオフ確認）に切り替えるか
    - 自動的に HANDOFF_REQUEST に倒すか
    を判断する小さなポリシークラス。
    
    実際の state 書き換えはここで行い、
    AICore 本体からは「何が起きたか」を受け取るだけにする。
    """
    
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
    
    def check_auto_handoff_from_unclear(
        self,
        call_id: str,
        state: ConversationState,
        intent: str,
    ) -> tuple[str, bool]:
        """
        unclear_streak >= 2 の場合に自動ハンドオフ発火を判定する。
        
        :param call_id: 通話ID
        :param state: 会話状態
        :param intent: 現在のintent
        :return: (updated_intent, auto_handoff_triggered)
        """
        unclear_streak = state.unclear_streak
        handoff_state = state.handoff_state
        
        # 【迷子判定】unclear_streak が一定回数以上で、handoff_state が idle または done の場合、
        # かつ明示的なハンドオフ要求でない場合、強制的に HANDOFF_REQUEST にして 0604 を出す
        if (unclear_streak >= 2 
            and handoff_state in ("idle", "done")
            and intent not in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO")):
            # 強制ハンドオフ発火時にメタ情報を付与
            state.meta["reason_for_handoff"] = "auto_unclear"
            state.meta["unclear_streak_at_trigger"] = unclear_streak
            self.logger.warning(
                "INTENT_FORCE_HANDOFF: call_id=%s unclear_streak=%d -> HANDOFF_REQUEST (tpl=0604) handoff_state=%s intent=%s meta.reason=auto_unclear unclear_streak_at_trigger=%d",
                call_id or "GLOBAL_CALL",
                unclear_streak,
                handoff_state,
                intent,
                unclear_streak
            )
            return "HANDOFF_REQUEST", True
        
        return intent, False
    
    def handle_not_heard_streak(
        self,
        call_id: str,
        state: ConversationState,
        template_ids: list[str],
        intent: str,
        base_intent: str,
    ) -> tuple[list[str], str, bool]:
        """
        not_heard_streak を更新し、必要に応じて 0604 に切り替える。
        
        :param call_id: 通話ID
        :param state: 会話状態
        :param template_ids: 現在のテンプレートIDリスト
        :param intent: 現在のintent
        :param base_intent: ベースとなるintent
        :return: (updated_template_ids, updated_intent, should_return_early)
        """
        # 【修正理由】template_ids が空の場合、_run_conversation_flow 内でフォールバックが実行されるが、
        # その後のストリーク処理で template_ids == ["110"] をチェックするため、
        # フォールバックで ["110"] が設定された場合にストリークが正しく動作する
        if template_ids == ["110"] and state.phase != "END":
            # 110 を返そうとしている回数をカウント
            not_heard_streak = state.not_heard_streak + 1
            state.not_heard_streak = not_heard_streak
            
            if not_heard_streak >= 2:
                # 2回目以降は 0604 に切り替え、handoff 確認フェーズへ
                state.not_heard_streak = 0
                state.handoff_state = "confirming"
                state.handoff_prompt_sent = True
                state.transfer_requested = False
                updated_template_ids = ["0604"]
                self.logger.debug(
                    "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                    call_id or "GLOBAL_CALL",
                    intent,
                    base_intent,
                    updated_template_ids,
                    state.phase,
                    state.handoff_state,
                    state.not_heard_streak,
                )
                return updated_template_ids, base_intent, True
        else:
            # 110 以外のテンプレートが出たらストリークをリセット
            state.not_heard_streak = 0
        
        return template_ids, intent, False
    
    def handle_unclear_streak(
        self,
        call_id: str,
        state: ConversationState,
        template_ids: list[str],
    ) -> None:
        """
        unclear_streak を更新する。
        
        :param call_id: 通話ID
        :param state: 会話状態
        :param template_ids: 現在のテンプレートIDリスト
        """
        # 【unclear_streak 管理】テンプレート選択後に unclear_streak を更新
        # tpl=110 が選ばれたときに +1
        if template_ids == ["110"]:
            unclear_streak = state.unclear_streak + 1
            state.unclear_streak = unclear_streak
            self.logger.warning(
                "UNCLEAR_STREAK_INC: call_id=%s unclear_streak=%d tpl=110",
                call_id or "GLOBAL_CALL",
                unclear_streak
            )
        else:
            # 通常の回答テンプレート（006, 006_SYS, 010, 004, 005 など）が選ばれたときにリセット
            # これらのテンプレートは「AI が内容を理解して回答できた」と判断
            normal_response_templates = ["006", "006_SYS", "010", "004", "005", "020", "021", "022", "023", 
                                        "040", "041", "042", "060", "061", "070", "071", "072", "080", "081", "082",
                                        "084", "085", "086", "087", "088", "089", "090", "091", "092", "099", "100",
                                        "101", "102", "103", "104", "0600", "0601", "0602", "0603", "0604"]
            if any(tid in normal_response_templates for tid in template_ids):
                if state.unclear_streak > 0:
                    self.logger.warning(
                        "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=tpl_%s",
                        call_id or "GLOBAL_CALL",
                        template_ids[0] if template_ids else "unknown"
                    )
                state.unclear_streak = 0
    
    def reset_unclear_streak_on_handoff_done(
        self,
        call_id: str,
        state: ConversationState,
        reason: str = "handoff_done",
    ) -> None:
        """
        handoff_state が done に遷移したときに unclear_streak をリセットする。
        
        :param call_id: 通話ID
        :param state: 会話状態
        :param reason: リセット理由
        """
        if state.unclear_streak > 0:
            self.logger.warning(
                "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=%s",
                call_id or "GLOBAL_CALL",
                reason
            )
        state.unclear_streak = 0


class HandoffStateMachine:
    """
    HANDOFF確認時のYES/NO/あいまい判定を担当する小さなステートマシン。
    
    もともと AICore._handle_handoff_confirm に書かれていたロジックを
    ほぼそのまま持つ。判定ロジックとstateの更新のみを行い、
    実際の処理（テンプレートレンダリング、コールバック呼び出し、自動切断予約など）
    は呼び出し側（AICore._handle_handoff_confirm）で行う。
    
    注意: YES/NO 判定の「どの日本語表現を拾うか」は intent_rules.interpret_handoff_reply
    に委譲している。retry 回数に応じて 0604 を出すか 081/082 で安全側転送に倒すかなどの
    「会話フロー」は、このクラス側で処理する。
    """
    
    def __init__(self, logger) -> None:
        self.logger = logger
    
    def handle_confirm(
        self,
        call_id: str,
        raw_text: str,
        intent: str,
        state: Dict[str, Any],
        contains_no_keywords: Callable[[str], bool],  # 互換性のため残すが、使用しない
    ) -> Tuple[List[str], str, bool, Dict[str, Any]]:
        """
        HANDOFF確認時の判定ロジック。
        
        :param call_id: 通話ID
        :param raw_text: 生テキスト
        :param intent: classify_intent の結果（HANDOFF_YES / HANDOFF_NO / UNKNOWN / NOT_HEARD など）
        :param state: session_states[call_id] の dict（直接 mutate して OK）
        :param contains_no_keywords: NO 判定用のヘルパ（互換性のため残すが、使用しない）
        :return: (template_ids, result_intent, transfer_requested, updated_state)
        """
        from .intent_rules import interpret_handoff_reply
        
        # intent_rules.interpret_handoff_reply を使って YES/NO 判定を統一
        hand_intent = interpret_handoff_reply(raw_text)
        
        # hand_intent が UNKNOWN の場合は元の intent を使用（retry ロジック用）
        if hand_intent == "UNKNOWN":
            hand_intent = intent
        
        # YES → transfer confirmed
        if hand_intent == "HANDOFF_YES":
            state["handoff_state"] = "done"
            state["handoff_retry_count"] = 0
            state["transfer_requested"] = True
            # handoff_state が done に遷移したときに unclear_streak をリセット
            # 注意: このリセット処理は AICore 側で行う（HandoffStateMachine は dict のみを扱う）
            if state.get("unclear_streak", 0) > 0:
                self.logger.warning(
                    "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=handoff_done",
                    call_id or "GLOBAL_CALL"
                )
            state["unclear_streak"] = 0
            # phase を更新（自動切断ロジック用）
            state["phase"] = "HANDOFF_DONE"
            state["handoff_completed"] = True
            template_ids = ["081", "082"]
            return template_ids, "HANDOFF_YES", True, state
        
        # NO → do not transfer, end conversation
        if hand_intent == "HANDOFF_NO":
            state["handoff_state"] = "done"
            state["handoff_retry_count"] = 0
            state["transfer_requested"] = False
            # handoff_state が done に遷移したときに unclear_streak をリセット
            if state.get("unclear_streak", 0) > 0:
                self.logger.warning(
                    "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=handoff_done",
                    call_id or "GLOBAL_CALL"
                )
            state["unclear_streak"] = 0
            # phase を更新（自動切断ロジック用）
            state["phase"] = "END"
            state["handoff_completed"] = True
            template_ids = ["086", "087"]
            return template_ids, "HANDOFF_NO", False, state
        
        # それ以外は「まだ YES/NO がはっきりしない」ものとして処理
        retry = state.get("handoff_retry_count", 0)
        
        # 【修正】UNKNOWN やその他のあいまいな応答の場合の処理を改善
        # 安全側に倒して、もう一度確認するか、有人へ繋ぐ
        if retry == 0:
            # 1回目のあいまい応答 → もう一度だけ 0604 で確認
            state["handoff_state"] = "confirming"
            state["handoff_retry_count"] = 1
            state["transfer_requested"] = False
            template_ids = ["0604"]
            self.logger.debug(
                "[NLG_DEBUG] handoff_confirm_retry call_id=%s intent=%s retry=%s",
                call_id or "GLOBAL_CALL",
                hand_intent,
                retry,
            )
            return template_ids, "HANDOFF_FALLBACK_REASK", False, state
        
        # 【修正】2回以上あいまいな場合、安全側に倒して有人へ繋ぐ
        # 拒否フローに入れるのではなく、ユーザーの意図が不明確な場合は有人へ繋ぐ
        self.logger.debug(
            "[NLG_DEBUG] handoff_confirm_ambiguous call_id=%s intent=%s retry=%s -> transfer for safety",
            call_id or "GLOBAL_CALL",
            hand_intent,
            retry,
        )
        state["handoff_state"] = "done"
        state["handoff_retry_count"] = 0
        state["transfer_requested"] = True
        # handoff_state が done に遷移したときに unclear_streak をリセット
        if state.get("unclear_streak", 0) > 0:
            self.logger.warning(
                "UNCLEAR_STREAK_RESET: call_id=%s unclear_streak=0 reason=handoff_done",
                call_id or "GLOBAL_CALL"
            )
        state["unclear_streak"] = 0
        # phase を更新（自動切断ロジック用）
        state["phase"] = "HANDOFF_DONE"
        state["handoff_completed"] = True
        template_ids = ["081", "082"]
        return template_ids, "HANDOFF_FALLBACK_YES", True, state


class AICore:
    # キーワードはインスタンス変数として初期化時にJSONから読み込まれる（後方互換性のためクラス変数としても定義）
    AFTER_085_NEGATIVE_KEYWORDS = []  # 初期化時にJSONから読み込まれる
    ENTRY_TRIGGER_KEYWORDS = []  # 初期化時にJSONから読み込まれる
    CLOSING_YES_KEYWORDS = []  # 初期化時にJSONから読み込まれる
    CLOSING_NO_KEYWORDS = []  # 初期化時にJSONから読み込まれる

    def __init__(self, init_clients: bool = True, client_id: str = "000"):
        self.logger = logging.getLogger(__name__)
        self._handoff_sm = HandoffStateMachine(self.logger)
        self._mis_guard = MisunderstandingGuard(self.logger)
        self.init_clients = init_clients
        self.client_id = client_id
        
        # クライアントごとの会話フロー・テンプレート・キーワードを読み込む
        self.flow = self._load_flow(client_id)
        self.templates = self._load_json(
            f"/opt/libertycall/config/clients/{client_id}/templates.json",
            default="/opt/libertycall/config/system/default_templates.json"
        )
        self.keywords = self._load_json(
            f"/opt/libertycall/config/clients/{client_id}/keywords.json",
            default="/opt/libertycall/config/system/default_keywords.json"
        )
        
        # キーワードをインスタンス変数として設定（後方互換性のため）
        self._load_keywords_from_config()
        self.call_id = None
        self.caller_number = None
        self.log_session_id = None  # 通話ログ用のセッションID（call_idがない場合に使用）
        self.session_states: Dict[str, Dict[str, Any]] = {}
        # 【追加】partial transcripts を保持（call_id ごとに管理）
        self.partial_transcripts: Dict[str, Dict[str, Any]] = {}
        self.tts_client = None
        self.voice_params = None
        self.audio_config = None
        self.debug_save_wav = False
        self.call_id = None
        self._wav_saved = False
        self._wav_chunk_counter = 0
        self.asr_model = None
        self.transfer_callback: Optional[Callable[[str], None]] = None
        self.hangup_callback: Optional[Callable[[str], None]] = None
        self._auto_hangup_timers: Dict[str, threading.Timer] = {}
        # 二重再生防止: on_call_start() を呼び出し済みの通話IDセット（全クライアント共通）
        self._call_started_calls: set[str] = set()
        # 二重再生防止: 冒頭テンプレート（000-002）を再生済みの通話IDセット（001専用）
        self._intro_played_calls: set[str] = set()
        
        # AI_CORE_VERSION ログ（編集した ai_core.py が読まれているか確認用）
        self.logger.info(
            "AI_CORE_VERSION: version=2025-12-01-auto-hangup hangup_callback=%s",
            "set" if self.hangup_callback else "none"
        )
        
        # ASR プロバイダの選択（デフォルト: google）
        asr_provider = os.getenv("LC_ASR_PROVIDER", "google").lower()
        
        # プロバイダの検証（local を含む不正な値はエラー）
        if asr_provider not in ["google", "whisper"]:
            raise ValueError(
                f"未知のASRプロバイダ: {asr_provider}\n"
                f"有効な値: 'google' または 'whisper'\n"
                f"（'local' はサポートされていません。'whisper' を使用してください。）"
            )
        
        self.asr_provider = asr_provider  # プロバイダを属性として保持
        self.logger.info(f"AICore: ASR provider = {asr_provider}")
        
        # ストリーミングモード判定
        self.streaming_enabled = os.getenv("LC_ASR_STREAMING_ENABLED", "0") == "1"
        
        if self.init_clients:
            # ASR モデルの初期化（プロバイダごとに完全に分離）
            if asr_provider == "google":
                # phrase_hints の読み込み
                phrase_hints = self._load_phrase_hints()
                
                try:
                    self.asr_model = GoogleASR(
                        language_code="ja",  # universal_speech_modelは"ja"をサポート（"ja-JP"は無効）
                        sample_rate=16000,  # Gateway側で既に16kHzに変換済み
                        phrase_hints=phrase_hints,
                        ai_core=self,  # AICore への参照を渡す（on_transcript 呼び出し用）
                        error_callback=self._on_asr_error,  # ASR エラー時のコールバック
                    )
                    self.logger.info("AICore: GoogleASR を初期化しました")
                except Exception as e:
                    error_msg = str(e)
                    if "was not found" in error_msg or "credentials" in error_msg.lower():
                        self.logger.error(
                            f"AICore: GoogleASR の初期化に失敗しました（認証エラー）: {error_msg}\n"
                            f"環境変数 LC_GOOGLE_PROJECT_ID と LC_GOOGLE_CREDENTIALS_PATH を確認してください。"
                        )
                    else:
                        self.logger.error(f"AICore: GoogleASR の初期化に失敗しました: {error_msg}")
                    raise
            elif asr_provider == "whisper":
                # WhisperLocalASR は whisper プロバイダ使用時のみインポート（google 使用時は絶対にインポートしない）
                from libertycall.asr.whisper_local import WhisperLocalASR  # type: ignore[import-untyped]
                
                self.logger.debug("AICore: Loading Whisper via WhisperLocalASR...")
                # WhisperLocalASR を使用（16kHz入力想定）
                self.asr_model = WhisperLocalASR(
                    model_name="base",
                    input_sample_rate=16000,  # Gateway側で既に16kHzに変換済み
                    language="ja",
                    device="cpu",
                    compute_type="int8",
                    temperature=0.0,
                    vad_filter=False,
                    vad_parameters=None
                )
                self.logger.info("AICore: WhisperLocalASR を初期化しました")
            
            if self.streaming_enabled:
                self.logger.info("AICore: ストリーミングASRモード有効")
            
            # TTS の初期化
            self._init_tts()
            
            # 起動時ログ（ASR_BOOT）を強制的に出力
            self.logger.info(f"ASR_BOOT: provider={asr_provider} streaming_enabled={self.streaming_enabled}")
        else:
            self.logger.info("AICore: init_clients=False のため ASR/TTS 初期化をスキップします (simulation mode)")
    
    def _load_phrase_hints(self) -> List[str]:
        """
        phrase_hints を設定ファイルから読み込む
        
        :return: phrase_hints のリスト
        """
        try:
            from libertycall.config.config import ASR_PHRASE_HINTS  # type: ignore[import-untyped]
            if ASR_PHRASE_HINTS:
                self.logger.info(f"AICore: phrase_hints を読み込みました: {ASR_PHRASE_HINTS}")
                return ASR_PHRASE_HINTS
        except (ImportError, AttributeError):
            pass
        
        # 環境変数から読み込む（カンマ区切り）
        env_phrase_hints = os.getenv("LC_ASR_PHRASE_HINTS")
        if env_phrase_hints:
            hints = [h.strip() for h in env_phrase_hints.split(",") if h.strip()]
            if hints:
                self.logger.info(f"AICore: phrase_hints を環境変数から読み込みました: {hints}")
                return hints
        
        return []
    
    def _init_tts(self):
        """
        Google TTS の初期化（別メソッドに分離）
        """
        if texttospeech is None:
            self.logger.debug("google-cloud-texttospeech 未導入のため TTS 初期化をスキップします。")
            return

        # ChatGPT音声風: TTSを完全非同期化するためのThreadPoolExecutorを初期化
        from concurrent.futures import ThreadPoolExecutor
        self.tts_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TTS")
        self.logger.debug("AICore: TTS ThreadPoolExecutor initialized (max_workers=2)")

        # WAV保存機能の設定
        self.debug_save_wav = os.getenv("LC_DEBUG_SAVE_WAV", "0") == "1"
        self.call_id = None
        self._wav_saved = False  # 1通話あたり最初の1回だけ保存
        self._wav_chunk_counter = 0
        
        # Google TTS設定
        self.tts_client = None
        self.voice_params = None
        self.audio_config = None
        try:
            self.tts_client = texttospeech.TextToSpeechClient()
        except DefaultCredentialsError as exc:
            self.logger.debug(
                "Google Application Default Credentials が未設定のため TTS を無効化します: %s",
                exc,
            )
        if self.tts_client:
            self.voice_params = texttospeech.VoiceSelectionParams(
                language_code="ja-JP", name="ja-JP-Neural2-B"
            )
            self.audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000
            )
    
    def set_call_id(self, call_id: str):
        """call_idを設定し、WAV保存フラグをリセット"""
        self.call_id = call_id
        self._wav_saved = False
        self._wav_chunk_counter = 0
    
    def _save_debug_wav(self, pcm16k_bytes: bytes):
        """Whisperに渡す直前のPCM音声をWAVファイルとして保存"""
        if not self.debug_save_wav:
            return
        
        # 1通話あたり最初の1回だけ保存（5-10秒分を想定）
        # ただし、短すぎる場合はスキップ
        sample_rate = 16000
        duration_sec = len(pcm16k_bytes) / 2 / sample_rate  # PCM16なので2バイト/サンプル
        
        if duration_sec < 1.0:  # 1秒未満はスキップ
            return
        
        # 保存先ディレクトリを作成
        debug_dir = Path("/opt/libertycall/debug_audio")
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名を生成
        call_id_str = self.call_id or "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._wav_chunk_counter += 1
        filename = f"call_{call_id_str}_chunk_{self._wav_chunk_counter:03d}_{timestamp}.wav"
        filepath = debug_dir / filename
        
        # WAVファイルに保存
        try:
            with wave.open(str(filepath), 'wb') as wav_file:
                wav_file.setnchannels(1)  # モノラル
                wav_file.setsampwidth(2)   # 16bit = 2 bytes
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm16k_bytes)
            
            # ログ出力
            self.logger.info(
                f"ASR_DEBUG: saved debug WAV for call_id={call_id_str} "
                f"path={filepath} sr={sample_rate} duration={duration_sec:.2f}s"
            )
            self._wav_saved = True
        except Exception as e:
            self.logger.error(f"Failed to save debug WAV: {e}")

    def _is_hallucination(self, text):
        """Whisperの幻聴（繰り返しノイズ）を判定"""
        if not text: return True
        # 1. 「おかげで、おかげで」のような繰り返しを検知
        if len(text) > 15 and len(set(text)) < 8:
            return True
        # 2. Whisper特有の幻聴ワード
        hallucination_words = ["おかげで", "ご視聴", "字幕", "チャンネル登録", "おやすみなさい"]
        for hw in hallucination_words:
            if text.count(hw) > 2: # 2回以上出てきたらアウト
                return True
        return False

    def _get_session_state(self, call_id: str) -> ConversationState:
        key = call_id or "GLOBAL_CALL"
        if key not in self.session_states:
            self.session_states[key] = {
                "phase": "ENTRY",
                "last_intent": None,
                "handoff_state": "idle",
                "handoff_retry_count": 0,
                "transfer_requested": False,
                "transfer_executed": False,
                "handoff_prompt_sent": False,
                "not_heard_streak": 0,
                "unclear_streak": 0,  # AI がよくわからない状態で返答した回数
                "handoff_completed": False,
                "last_ai_templates": [],
                "meta": {},
            }
        return ConversationState(self.session_states[key])

    def _reset_session_state(self, call_id: Optional[str]) -> None:
        """
        セッション状態をリセット（通話終了時など）
        
        注意: reset_call() から呼ばれるため、基本的には通話終了時のみ呼ばれる。
        ただし、再接続時に call_id が変わらない場合は、on_call_end() で明示的にクリアすることを推奨。
        """
        if not call_id:
            return
        self.session_states.pop(call_id, None)
        # セッション状態のみクリア（フラグは on_call_end() でクリア）
    
    def on_call_end(self, call_id: Optional[str], source: str = "unknown") -> None:
        """
        通話終了時の処理（明示的なクリーンアップ）
        
        :param call_id: 通話ID
        :param source: 呼び出し元（デバッグ用: "_complete_console_call" / "_handle_hangup" など）
        """
        if not call_id:
            return
        
        # 終了時点の状態を取得（ログ用）
        try:
            state = self._get_session_state(call_id)
            phase_at_end = state.phase
            # 【修正4】state.meta に client_id があればそれを使う（callごとにclientが変わる構成に対応）
            client_id_from_state = state.meta.get("client_id") if hasattr(state, 'meta') and state.meta else None
        except Exception:
            phase_at_end = "unknown"
            client_id_from_state = None
        # client_id の優先順位: state.meta > self.client_id > "000"
        effective_client_id = client_id_from_state or self.client_id or "000"
        
        # 【改善2・3】通話終了時のみフラグをクリア（再接続時の誤クリアを防ぐ）
        was_started = call_id in self._call_started_calls
        was_intro_played = call_id in self._intro_played_calls
        
        self._call_started_calls.discard(call_id)
        self._intro_played_calls.discard(call_id)
        
        # ログ出力（デバッグ強化）
        self.logger.info(
            f"[AICORE] on_call_end() call_id={call_id} source={source} client_id={effective_client_id} "
            f"phase={phase_at_end} "
            f"_call_started_calls={was_started} _intro_played_calls={was_intro_played} -> cleared"
        )

    def _load_flow(self, client_id: str) -> dict:
        """
        クライアントごとの会話フローを読み込む
        
        :param client_id: クライアントID
        :return: 会話フロー設定（dict）
        """
        path = f"/opt/libertycall/config/clients/{client_id}/flow.json"
        default_path = "/opt/libertycall/config/system/default_flow.json"
        
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                flow = json.load(f)
                version = flow.get("version", "unknown")
                self.logger.info(f"[FLOW] client={client_id} version={version} loaded")
                return flow
        else:
            if os.path.exists(default_path):
                with open(default_path, "r", encoding="utf-8") as f:
                    flow = json.load(f)
                    self.logger.warning(f"[FLOW] client={client_id} missing, loaded default version={flow.get('version', 'unknown')}")
                    return flow
            else:
                self.logger.error(f"[FLOW] client={client_id} missing and default not found, using empty flow")
                return {}
    
    def _load_json(self, path: str, default: str = None) -> dict:
        """
        汎用JSON読み込みヘルパー
        
        :param path: JSONファイルのパス
        :param default: フォールバック用のデフォルトパス
        :return: JSONデータ（dict）
        """
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        elif default and os.path.exists(default):
            with open(default, "r", encoding="utf-8") as f:
                self.logger.debug(f"[FLOW] Using default file: {default}")
                return json.load(f)
        return {}
    
    def _load_keywords_from_config(self) -> None:
        """
        keywords.jsonからキーワードを読み込んでインスタンス変数に設定
        """
        if not self.keywords:
            self.logger.warning("[FLOW] keywords not loaded, using empty lists")
            self.AFTER_085_NEGATIVE_KEYWORDS = []
            self.ENTRY_TRIGGER_KEYWORDS = []
            self.CLOSING_YES_KEYWORDS = []
            self.CLOSING_NO_KEYWORDS = []
            return
        
        self.AFTER_085_NEGATIVE_KEYWORDS = self.keywords.get("AFTER_085_NEGATIVE_KEYWORDS", [])
        self.ENTRY_TRIGGER_KEYWORDS = self.keywords.get("ENTRY_TRIGGER_KEYWORDS", [])
        self.CLOSING_YES_KEYWORDS = self.keywords.get("CLOSING_YES_KEYWORDS", [])
        self.CLOSING_NO_KEYWORDS = self.keywords.get("CLOSING_NO_KEYWORDS", [])
        
        self.logger.debug(
            f"[FLOW] Keywords loaded: ENTRY_TRIGGER={len(self.ENTRY_TRIGGER_KEYWORDS)}, "
            f"CLOSING_YES={len(self.CLOSING_YES_KEYWORDS)}, CLOSING_NO={len(self.CLOSING_NO_KEYWORDS)}, "
            f"AFTER_085_NEGATIVE={len(self.AFTER_085_NEGATIVE_KEYWORDS)}"
        )
    
    def reload_flow(self) -> None:
        """
        会話フロー・テンプレート・キーワードを再読み込みする
        """
        self.flow = self._load_flow(self.client_id)
        self.templates = self._load_json(
            f"/opt/libertycall/config/clients/{self.client_id}/templates.json",
            default="/opt/libertycall/config/system/default_templates.json"
        )
        self.keywords = self._load_json(
            f"/opt/libertycall/config/clients/{self.client_id}/keywords.json",
            default="/opt/libertycall/config/system/default_keywords.json"
        )
        self._load_keywords_from_config()
        self.logger.info(f"[FLOW] reloaded for client={self.client_id}")
    
    def set_client_id(self, client_id: str) -> None:
        """
        クライアントIDを変更して会話フローを再読み込みする
        
        :param client_id: 新しいクライアントID
        """
        self.client_id = client_id
        self.reload_flow()

    def _contains_keywords(self, normalized_text: str, keywords: List[str]) -> bool:
        if not normalized_text:
            return False
        return any(k for k in keywords if k and k in normalized_text)

    def _render_templates(self, template_ids: List[str]) -> str:
        texts: List[str] = []
        for template_id in template_ids:
            template_text = get_response_template(template_id)
            if template_text:
                texts.append(template_text)
        return " ".join(texts).strip()

    def _synthesize_template_audio(self, template_id: str) -> Optional[bytes]:
        """
        テンプレIDから音声を合成する
        
        :param template_id: テンプレID
        :return: 音声データ（bytes）または None
        """
        if not self.tts_client or texttospeech is None:
            return None
        
        # まず self.templates（クライアント固有）から読み込む
        cfg = None
        if self.templates and template_id in self.templates:
            cfg = self.templates[template_id]
            self.logger.debug(f"[TEMPLATE] Loaded {template_id} from client templates (client_id={self.client_id})")
        
        # クライアント固有にない場合はグローバル TEMPLATE_CONFIG から読み込む
        if not cfg:
            cfg = get_template_config(template_id)
            if cfg:
                self.logger.debug(f"[TEMPLATE] Loaded {template_id} from global TEMPLATE_CONFIG")
        
        if not cfg:
            self.logger.warning(f"[TEMPLATE] Template {template_id} not found in client templates or global config")
            return None
        
        text = cfg.get("text", "")
        if not text:
            return None
        
        voice_name = cfg.get("voice", "ja-JP-Neural2-B")
        speaking_rate = cfg.get("rate", 1.1)
        
        # voice_name から language_code を抽出（例: "ja-JP-Neural2-B" -> "ja-JP"）
        language_code = "ja-JP"
        if "-" in voice_name:
            parts = voice_name.split("-")
            if len(parts) >= 2:
                language_code = f"{parts[0]}-{parts[1]}"
        
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice_params = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                speaking_rate=speaking_rate
            )
            response = self.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config
            )
            return response.audio_content
        except Exception as e:
            self.logger.exception(f"TTS synthesis failed for template_id={template_id}: {e}")
            return None

    def _synthesize_template_sequence(self, template_ids: List[str]) -> Optional[bytes]:
        """
        テンプレIDのリストから順番に音声を合成して結合する
        
        :param template_ids: テンプレIDのリスト
        :return: 結合された音声データ（bytes）または None
        """
        if not template_ids:
            return None
        
        audio_chunks: List[bytes] = []
        for template_id in template_ids:
            audio = self._synthesize_template_audio(template_id)
            if audio:
                audio_chunks.append(audio)
        
        if not audio_chunks:
            return None
        
        # 複数の音声チャンクを結合
        if len(audio_chunks) == 1:
            return audio_chunks[0]
        
        # 複数チャンクを結合（単純にバイト列を連結）
        return b"".join(audio_chunks)

    def _append_call_log(self, role: str, text: str, template_id: Optional[str] = None) -> None:
        """
        通話ログを 1行追記する。
        形式: [YYYY-mm-dd HH:MM:SS] [caller] ROLE (tpl=XXX) text
        """
        # call_id / log_session_id はここで例外を投げないように注意する
        try:
            client_id = getattr(self, "client_id", "000")
            if not client_id:
                client_id = "000"
            caller = getattr(self, "caller_number", None) or "-"
        except Exception:
            client_id = "000"
            caller = "-"
        
        # ログディレクトリの作成
        try:
            base_dir = os.path.join("/opt", "libertycall", "logs", "calls", client_id)
            os.makedirs(base_dir, exist_ok=True)
        except OSError:
            # ディレクトリ作成に失敗したら諦める（会話は止めない）
            self.logger.exception("CALL_LOGGING_ERROR: failed to create log directory")
            return
        
        # ファイル名を決定
        call_id_str = getattr(self, "call_id", None)
        # TEMP_CALLやunknownは無効なcall_idとして扱う
        if call_id_str and str(call_id_str).strip() and str(call_id_str).lower() not in ("unknown", "temp_call"):
            filename = f"{call_id_str}.log"
        else:
            # セッションIDベースの一時ID（TEMP_CALLの場合は正式なcall_idを生成）
            if not getattr(self, "log_session_id", None):
                now = datetime.now()
                self.log_session_id = now.strftime("CALL_%Y%m%d_%H%M%S%f")
            filename = f"{self.log_session_id}.log"
        
        log_path = os.path.join(base_dir, filename)
        
        # 実際の書き込み
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tpl_suffix = f" (tpl={template_id})" if template_id else ""
            line = f"[{now_str}] [{caller}] {role}{tpl_suffix} {text}\n"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            self.logger.exception("CALL_LOGGING_ERROR: failed to write log file")
        except Exception:
            # 予期せぬ例外もログには残すが、会話は止めない
            self.logger.exception("CALL_LOGGING_ERROR in _append_call_log")

    def _trigger_transfer(self, call_id: str) -> None:
        """
        転送をトリガーする（_generate_reply の末尾などから呼ばれる）
        
        注意: このメソッドは後方互換性のため残していますが、
        新しいコードでは _trigger_transfer_if_needed を使用してください。
        """
        self.logger.info("TRANSFER_TRIGGER_START: call_id=%s", call_id)
        if hasattr(self, "transfer_callback") and self.transfer_callback:
            try:
                self.logger.info("TRANSFER_TRIGGER: calling transfer_callback call_id=%s", call_id)
                self.transfer_callback(call_id)
                self.logger.info("TRANSFER_TRIGGER_DONE: transfer_callback completed call_id=%s", call_id)
            except Exception as exc:
                self.logger.exception("TRANSFER_TRIGGER_ERROR: transfer_callback error call_id=%s error=%r", call_id, exc)
        else:
            self.logger.warning("TRANSFER_TRIGGER_SKIP: transfer requested but no callback is set call_id=%s", call_id)

    def _trigger_transfer_if_needed(self, call_id: str, state: ConversationState) -> None:
        """
        transfer_requested / transfer_executed / handoff_state を見て、
        必要な場合のみ transfer_callback を 1 回だけ呼び出すヘルパー。
        
        このメソッドを通してのみ transfer_callback を実行する想定。
        既存挙動を変えないことを最優先とし、
        条件は現行コードに合わせて調整する。
        """
        if not getattr(self, "transfer_callback", None):
            return
        
        # すでに実行済みなら何もしない
        if state.transfer_executed:
            return
        
        # 転送要求が立っていないなら何もしない
        if not state.transfer_requested:
            return
        
        try:
            self.logger.info(
                "AICore: TRIGGER_TRANSFER call_id=%s phase=%s handoff_state=%s",
                call_id,
                state.phase,
                state.handoff_state,
            )
            self.transfer_callback(call_id)  # type: ignore[misc]
            state.transfer_executed = True
        except Exception:
            self.logger.exception(
                "AICore: transfer_callback failed call_id=%s", call_id
            )

    def _schedule_auto_hangup(self, call_id: str, delay_sec: float = 60.0) -> None:
        """
        END フェーズ遷移後の自動切断タイマーをセットする
        
        注意: 既存のタイマーがある場合は自動的にキャンセルしてから新しいタイマーをセットします。
        これにより、以下のシーケンスでも正しく動作します：
        1. _schedule_auto_hangup(call_id, 60.0) → timer起動
        2. 50秒後、ユーザーが「やっぱり話したい」と発話
        3. _generate_reply が再度 _schedule_auto_hangup を呼ぶ → 既存timerをキャンセル
        4. 新しいtimerが60秒でセット
        5. その10秒後、ユーザーが切断 → reset_call が呼ばれる → timerをキャンセル
        
        reset_call でも timer.cancel() を実行していますが、これは通話終了時のクリーンアップとして
        実行されるもので、_schedule_auto_hangup 内のキャンセル処理とは競合しません。
        """
        key = call_id or "GLOBAL_CALL"

        # ログ：入口
        self.logger.info(
            "AUTO_HANGUP_SCHEDULE_REQUEST: call_id=%s delay=%.1f hangup_cb=%s",
            key,
            delay_sec,
            "set" if self.hangup_callback else "none",
        )

        # callback 未設定なら何もしない
        if not self.hangup_callback:
            self.logger.warning(
                "AUTO_HANGUP_SKIP: call_id=%s reason=no_hangup_callback", key
            )
            return

        # 既存タイマーがあればキャンセル
        old_timer = self._auto_hangup_timers.get(key)
        if old_timer is not None:
            try:
                old_timer.cancel()
                self.logger.info(
                    "AUTO_HANGUP_CANCEL_PREV: call_id=%s", key
                )
            except Exception as e:
                self.logger.warning(
                    "AUTO_HANGUP_CANCEL_PREV_ERROR: call_id=%s error=%r",
                    key, e
                )

        def _do_hangup() -> None:
            self.logger.info(
                "AUTO_HANGUP_TRIGGER: call_id=%s", key
            )
            try:
                if self.hangup_callback:
                    self.hangup_callback(key)  # 実際の切断処理は gateway 側
            except Exception as e:
                self.logger.exception(
                    "AUTO_HANGUP_CALLBACK_ERROR: call_id=%s error=%r",
                    key, e
                )
            finally:
                # 実行後に辞書から消す
                try:
                    self._auto_hangup_timers.pop(key, None)
                except Exception:
                    pass

        t = threading.Timer(delay_sec, _do_hangup)
        t.daemon = True  # 念のため
        self._auto_hangup_timers[key] = t
        t.start()

        self.logger.info(
            "AUTO_HANGUP_SCHEDULED: call_id=%s delay=%.1f",
            key,
            delay_sec,
        )

    def on_call_start(self, call_id: str, client_id: str = None, **kwargs) -> None:
        """
        通話開始時の処理
        
        :param call_id: 通話ID
        :param client_id: クライアントID（省略時は self.client_id を使用）
        :param kwargs: その他の引数
        """
        effective_client_id = client_id or self.client_id or "000"
        
        # 【診断用】強制的に可視化（logger設定に依存しない）
        print(f"[DEBUG_PRINT] on_call_start called call_id={call_id} client_id={effective_client_id} self.client_id={self.client_id}", flush=True)
        
        # 【改善1】on_call_start() 自体の重複呼び出し防止（全クライアント共通）
        if call_id in self._call_started_calls:
            print(f"[DEBUG_PRINT] on_call_start=skipped call_id={call_id} reason=already_called", flush=True)
            self.logger.info(f"[AICORE] on_call_start=skipped call_id={call_id} reason=already_called")
            return
        
        print(f"[DEBUG_PRINT] on_call_start proceeding call_id={call_id} effective_client_id={effective_client_id}", flush=True)
        self.logger.info(f"[AICORE] on_call_start() call_id={call_id} client_id={effective_client_id}")
        # 呼び出し済みフラグを設定（001以外でも設定）
        self._call_started_calls.add(call_id)
        
        # 【最終チェック1】state.meta["client_id"] をセット（ログ用の一貫性確保）
        state = self._get_session_state(call_id)
        if not hasattr(state, 'meta') or state.meta is None:
            state.meta = {}
        state.meta["client_id"] = effective_client_id
        
        # クライアント001専用：録音告知＋LibertyCall挨拶を再生
        if effective_client_id == "001":
            print(f"[DEBUG_PRINT] client_id=001 detected, proceeding with intro template", flush=True)
            # 【改善1】001の場合だけ、phase を一旦 "INTRO" にしておく
            state = self._get_session_state(call_id)
            state.phase = "INTRO"
            self.logger.debug(f"[AICORE] Phase set to INTRO for call_id={call_id} (client_id=001, will change to ENTRY after intro)")
            # 【改善3】テンプレート存在チェックを緩和（解決は下層に任せる）
            # tts_callback が設定されている場合のみ実行
            if hasattr(self, 'tts_callback') and self.tts_callback:
                print(f"[DEBUG_PRINT] tts_callback is set, calling with template 000-002", flush=True)
                try:
                    print(f"[DEBUG_PRINT] intro=queued template_id=000-002 call_id={call_id}", flush=True)
                    self.logger.info(f"[AICORE] intro=queued template_id=000-002 call_id={call_id}")
                    self.tts_callback(call_id, None, ["000-002"], False)  # type: ignore[misc, attr-defined]
                    # 再生済みフラグを設定
                    self._intro_played_calls.add(call_id)
                    print(f"[DEBUG_PRINT] intro=sent template_id=000-002 call_id={call_id}", flush=True)
                    self.logger.info(f"[AICORE] intro=sent template_id=000-002 call_id={call_id}")
                    
                    # 【改善1】intro送信完了後、ENTRYフェーズへ遷移
                    state = self._get_session_state(call_id)
                    state.phase = "ENTRY"
                    self.logger.debug(f"[AICORE] Phase changed from INTRO to ENTRY for call_id={call_id} (after intro sent)")
                    
                    # 【改善2】intro送信完了
                    # 注意: ENTRYテンプレート（004/005）は既存の動作（on_transcript() でユーザー発話を受けた時）に任せる
                    # これにより、introが再生中にENTRYテンプレートが被ることを防ぐ
                    self.logger.debug(f"[AICORE] intro_sent entry_templates=deferred (will be sent by on_transcript when user speaks) call_id={call_id}")
                    
                except Exception as e:
                    self.logger.exception(f"[AICORE] intro=error template_id=000-002 call_id={call_id} error={e}")
                    # エラー時もENTRYフェーズへ遷移
                    state = self._get_session_state(call_id)
                    state.phase = "ENTRY"
            else:
                print(f"[DEBUG_PRINT] intro=error tts_callback not set call_id={call_id}", flush=True)
                self.logger.warning("[AICORE] intro=error tts_callback not set, cannot send template 000-002")
                # tts_callback未設定でもENTRYフェーズへ遷移
                state = self._get_session_state(call_id)
                state.phase = "ENTRY"
        else:
            # 001以外は即座にENTRYフェーズへ遷移（既存の動作）
            state = self._get_session_state(call_id)
            state.phase = "ENTRY"
            self.logger.debug(f"[AICORE] Phase set to ENTRY for call_id={call_id} (client_id={effective_client_id})")

    def _handle_entry_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        intent = classify_intent(raw_text)
        # ノイズ・聞き取れないケースの処理（最優先）
        if intent == "NOT_HEARD":
            state.phase = "QA"
            state.last_intent = intent
            template_ids = select_template_ids(intent, raw_text)
            return intent, template_ids, False
        if intent == "GREETING":
            state.phase = "QA"
            state.last_intent = intent
            return intent, ["004", "005"], False
        if self._contains_keywords(normalized_text, self.ENTRY_TRIGGER_KEYWORDS):
            state.phase = "ENTRY_CONFIRM"
            state.last_intent = "INQUIRY"
            return "INQUIRY", ["006"], False
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_qa_phase(
        self,
        call_id: str,
        raw_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        通常QAフェーズ + HANDOFF導入フェーズ。
        戻り値: (intent, template_ids, transfer_requested)
        """
        intent = classify_intent(raw_text) or "UNKNOWN"
        handoff_state = state.handoff_state
        transfer_requested = state.transfer_requested
        
        # --------------------------------------------------
        # すでに handoff 完了済み → 0604/104 は二度と出さない
        # --------------------------------------------------
        if handoff_state == "done":
            template_ids = select_template_ids(intent, raw_text)
            # 念のため 0604/104 を強制フィルタ
            template_ids = [tid for tid in template_ids if tid not in ("0604", "104")]
            if intent == "SALES_CALL":
                last_intent = state.last_intent
                if last_intent == "SALES_CALL":
                    state.phase = "END"
                else:
                    state.phase = "AFTER_085"
            elif intent == "END_CALL":
                state.phase = "END"
            else:
                state.phase = "AFTER_085"
            state.last_intent = intent
            return intent, template_ids, transfer_requested
        
        # --------------------------------------------------
        # handoff_state == "confirming" の処理は別関数で扱う想定
        # （_generate_reply から _handle_handoff_confirm を呼ぶ）
        # --------------------------------------------------
        
        # --------------------------------------------------
        # 通常QA: intent_rules に任せるが、0604/104 はこのフェーズでは使わない想定
        # --------------------------------------------------
        # 温度の低いリード（INQUIRY_PASSIVE）の処理
        if intent == "INQUIRY_PASSIVE":
            # 089または090をランダムで返す（intent_rules.select_template_idsで既に処理済み）
            template_ids = select_template_ids(intent, raw_text)
            state.phase = "QA"  # QA継続
            state.last_intent = intent
            return intent, template_ids, transfer_requested
        
        template_ids = select_template_ids(intent, raw_text)
        if intent == "SALES_CALL":
            last_intent = state.last_intent
            if last_intent == "SALES_CALL":
                state.phase = "END"
            else:
                state.phase = "AFTER_085"
        elif intent == "END_CALL":
            state.phase = "END"
        else:
            state.phase = "AFTER_085"
        state.last_intent = intent
        return intent, template_ids, transfer_requested

    def _handle_after_085_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        # SALES_CALL の場合は、前回の intent を確認して応答を決定
        intent = classify_intent(raw_text)
        
        # 【修正】HANDOFF_REQUEST は phase に関係なく、常に 0604 を返す
        # handoff_state == "done" の状態でも「担当者お願いします」と言われたら、再度確認文を返す
        # handoff_state が idle または done の場合のみ処理（confirming 中は既存のハンドオフ確認フローに任せる）
        # 念のため、handoff_state が未設定の場合は "idle" をデフォルト値として使用
        if intent == "HANDOFF_REQUEST" and state.handoff_state in ("idle", "done"):
            state.handoff_state = "confirming"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = True
            state.transfer_requested = False
            state.transfer_executed = False
            template_ids = ["0604"]
            state.last_intent = intent
            return intent, template_ids, False
        
        if intent == "SALES_CALL":
            last_intent = state.last_intent
            if last_intent == "SALES_CALL":
                # 2回目の営業電話発話（「はい営業です」など）の場合は END に移行
                state.phase = "END"
                template_ids = select_template_ids(intent, raw_text)
                # handoff_state == "done" の場合は 0604/104 を出さない
                if state.handoff_state == "done":
                    template_ids = [tid for tid in template_ids if tid not in ["0604", "104"]]
                state.last_intent = intent
                return intent, template_ids, False
        
        if self._contains_keywords(normalized_text, self.AFTER_085_NEGATIVE_KEYWORDS):
            state.phase = "CLOSING"
            return "END_CALL", ["013"], False
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_entry_confirm_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        if self._contains_keywords(normalized_text, self.CLOSING_YES_KEYWORDS):
            state.phase = "QA"
            state.last_intent = "INQUIRY"
            return "INQUIRY", ["010"], False
        if self._contains_keywords(normalized_text, self.CLOSING_NO_KEYWORDS):
            state.phase = "END"
            state.last_intent = "END_CALL"
            return "END_CALL", ["087", "088"], False
        # ユーザー返答がある場合はQAへ、ない場合はWAITINGへ
        # 注意: 実際のWAITING処理はrealtime_gateway.py側でTTS送信後の待機として実装
        # ここでは、テンプレート006にwait_time_afterが設定されていることを前提にQAへ遷移
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)
    
    def _handle_waiting_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        WAITINGフェーズ: ユーザー返答待ち（1.5〜2.0秒待機）
        実際の待機処理はrealtime_gateway.py側で実装
        """
        # ユーザー音声が検知された場合はQAへ
        if raw_text and len(raw_text.strip()) > 0:
            state.phase = "QA"
            return self._handle_qa_phase(call_id, raw_text, state)
        # 返答なしの場合はNOT_HEARDへ
        state.phase = "NOT_HEARD"
        return "NOT_HEARD", ["110"], False
    
    def _handle_not_heard_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        NOT_HEARDフェーズ: 聞き取れなかった場合
        """
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_closing_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        if self._contains_keywords(normalized_text, self.CLOSING_YES_KEYWORDS):
            state.phase = "HANDOFF"
            state.last_intent = "SETUP"
            return "SETUP", ["060", "061", "062", "104"], False
        if self._contains_keywords(normalized_text, self.CLOSING_NO_KEYWORDS):
            state.phase = "END"
            state.last_intent = "END_CALL"
            return "END_CALL", ["087", "088"], False
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_handoff_confirm(
        self,
        call_id: str,
        raw_text: str,
        intent: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], str, bool]:
        """
        HANDOFF 確認時のラッパー。
        実際の判定ロジックは HandoffStateMachine に委譲する。
        """
        from .intent_rules import normalize_text
        
        # intent が UNKNOWN の場合はここで一度だけ再判定（既存ロジック踏襲）
        # 注意: handoff_state == "confirming" の場合は context="handoff_confirming" を渡す
        if intent == "UNKNOWN":
            from .intent_rules import classify_intent
            intent = classify_intent(raw_text, context="handoff_confirming") or "UNKNOWN"
        
        normalized = normalize_text(raw_text)
        
        def contains_no_keywords(text: str) -> bool:
            # 既存の self._contains_keywords(normalized, self.CLOSING_NO_KEYWORDS) を包むヘルパ
            return self._contains_keywords(text, self.CLOSING_NO_KEYWORDS)
        
        template_ids, result_intent, transfer_requested, updated_raw = (
            self._handoff_sm.handle_confirm(
                call_id=call_id,
                raw_text=raw_text,
                intent=intent,
                state=state.raw,
                contains_no_keywords=lambda text=normalized: contains_no_keywords(text),
            )
        )
        
        # updated_raw は state.raw と同じ参照なので、state をそのまま使う
        updated_state = state
        
        # テンプレートレンダリング
        reply_text = self._render_templates(template_ids)
        
        # 転送コールバックの実行は on_transcript 内で TTS 送信後に実行される
        # （transfer_requested フラグを on_transcript に渡し、_send_tts 内でTTS送信完了後に転送処理を開始）
        # transfer_requested は HandoffStateMachine で既に設定されている
        if result_intent in ("HANDOFF_YES", "HANDOFF_FALLBACK_YES"):
            # handoff_state が done に遷移したときに unclear_streak をリセット
            self._mis_guard.reset_unclear_streak_on_handoff_done(call_id, updated_state)
            # _trigger_transfer_if_needed は on_transcript 内で TTS 送信後に実行されるため、ここでは呼ばない
        
        # 自動切断予約（HANDOFF_NO の場合）
        if result_intent == "HANDOFF_NO":
            key = call_id or "GLOBAL_CALL"
            if self.hangup_callback:
                self.logger.info(
                    "AUTO_HANGUP_DIRECT_SCHEDULE: call_id=%s delay=60.0",
                    key,
                )
                try:
                    self._schedule_auto_hangup(key, delay_sec=60.0)
                except Exception as e:
                    self.logger.exception(
                        "AUTO_HANGUP_DIRECT_SCHEDULE_ERROR: call_id=%s error=%r",
                        key, e
                    )
            else:
                self.logger.warning(
                    "AUTO_HANGUP_DIRECT_SKIP: call_id=%s reason=no_hangup_callback",
                    key,
                )
        
        # state.raw は既に self.session_states[key] を参照しているため、明示的な代入は不要
        
        return reply_text, template_ids, result_intent, transfer_requested

    def _handle_handoff_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        Wrapper while confirming handoff (HANDOFF_CONFIRM_WAIT phase).
        Actual decision logic is delegated to _handle_handoff_confirm.
        """
        from .intent_rules import classify_intent
        
        intent = classify_intent(raw_text) or "UNKNOWN"
        reply_text, template_ids, result_intent, transfer_requested = self._handle_handoff_confirm(
            call_id, raw_text, intent, state
        )
        
        if result_intent == "HANDOFF_YES":
            state.phase = "HANDOFF_DONE"
            state.last_intent = "HANDOFF_YES"
            state.handoff_completed = True
            state.transfer_requested = True
            # handoff_state が done に遷移したときに unclear_streak をリセット
            self._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)
            # _trigger_transfer_if_needed は on_transcript 内で TTS 送信後に実行されるため、ここでは呼ばない
        elif result_intent == "HANDOFF_FALLBACK_YES":
            # 【追加】安全側に倒して有人へ繋ぐ場合
            state.phase = "HANDOFF_DONE"
            state.last_intent = "HANDOFF_YES"
            state.handoff_completed = True
            state.transfer_requested = True
            # handoff_state が done に遷移したときに unclear_streak をリセット
            self._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)
            # _trigger_transfer_if_needed は on_transcript 内で TTS 送信後に実行されるため、ここでは呼ばない
        elif result_intent in ("HANDOFF_NO", "HANDOFF_FALLBACK_NO"):
            state.phase = "END"
            state.last_intent = "END_CALL"
            state.handoff_completed = True
        else:
            state.phase = "HANDOFF_CONFIRM_WAIT"
            state.last_intent = "HANDOFF_REQUEST"
        
        # state.raw は既に self.session_states[key] を参照しているため、明示的な代入は不要
        return result_intent, template_ids, transfer_requested

    def _run_conversation_flow(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[List[str], str, bool]:
        state = self._get_session_state(call_id)
        normalized = normalize_text(raw_text)
        phase = state.phase
        intent = "UNKNOWN"
        template_ids: List[str] = []
        transfer_requested = False

        if phase == "END":
            return [], "END_CALL", False
        if phase == "INTRO":
            # INTROフェーズ中は何も返さない（intro再生中）
            self.logger.debug(f"[AICORE] Phase=INTRO, skipping response (intro playing) call_id={call_id}")
            return [], "UNKNOWN", False
        if phase == "ENTRY":
            intent, template_ids, transfer_requested = self._handle_entry_phase(call_id, raw_text, normalized, state)
        elif phase == "ENTRY_CONFIRM":
            intent, template_ids, transfer_requested = self._handle_entry_confirm_phase(call_id, raw_text, normalized, state)
        elif phase == "WAITING":
            intent, template_ids, transfer_requested = self._handle_waiting_phase(call_id, raw_text, normalized, state)
        elif phase == "NOT_HEARD":
            intent, template_ids, transfer_requested = self._handle_not_heard_phase(call_id, raw_text, normalized, state)
        elif phase == "QA":
            intent, template_ids, transfer_requested = self._handle_qa_phase(call_id, raw_text, state)
        elif phase == "AFTER_085":
            intent, template_ids, transfer_requested = self._handle_after_085_phase(call_id, raw_text, normalized, state)
        elif phase == "CLOSING":
            intent, template_ids, transfer_requested = self._handle_closing_phase(call_id, raw_text, normalized, state)
        elif phase == "HANDOFF" or phase == "HANDOFF_CONFIRM_WAIT":
            intent, template_ids, transfer_requested = self._handle_handoff_phase(call_id, raw_text, normalized, state)
        else:
            state.phase = "QA"
            intent, template_ids, transfer_requested = self._handle_qa_phase(call_id, raw_text, state)

        if not template_ids and state.phase != "END":
            intent = intent or "UNKNOWN"
            # HANDOFF 系のときは 110 を当てず、上位ロジックに任せる
            if intent in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO"):
                template_ids = []
            else:
                # 無言を絶対出さないフォールバック
                template_ids = ["110"]
        
        # 直前のAIテンプレートをstateに保存（HANDOFF判定用）
        state.last_ai_templates = template_ids
        
        return template_ids, intent, transfer_requested

    def _generate_reply(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[str, List[str], str, bool]:
        """
        Core conversation flow entry point.
        - intent classification
        - HANDOFF state (idle / confirming / done)
        - normal template selection
        """
        from .intent_rules import classify_intent
        
        state = self._get_session_state(call_id)
        handoff_state = state.handoff_state
        transfer_requested = state.transfer_requested
        
        # handoff_state == "confirming" の場合は context="handoff_confirming" を渡す
        # これにより、「はい」などの肯定応答が HANDOFF_YES として正しく判定される
        context = "handoff_confirming" if handoff_state == "confirming" else None
        intent = classify_intent(raw_text, context=context) or "UNKNOWN"
        
        # 【迷子判定】unclear_streak が一定回数以上で、handoff_state が idle または done の場合、
        # かつ明示的なハンドオフ要求でない場合、強制的に HANDOFF_REQUEST にして 0604 を出す
        intent, auto_handoff_triggered = self._mis_guard.check_auto_handoff_from_unclear(
            call_id, state, intent
        )
        
        # 【保険ロジック】handoff_state が confirming 以外なのに HANDOFF_YES が来た場合は、
        # 新しいハンドオフリクエストとして扱う（0604 を出す）ようにする
        if intent == "HANDOFF_YES" and handoff_state != "confirming":
            self.logger.info(
                "INTENT_ADJUST: HANDOFF_YES received outside confirming state (handoff_state=%s). Downgrading to HANDOFF_REQUEST.",
                handoff_state
            )
            intent = "HANDOFF_REQUEST"
        
        # 【新規】担当者不在時は 0605 でAI継続を案内
        if intent == "HANDOFF_REQUEST" and not getattr(self, "transfer_callback", None):
            self.logger.warning(
                "[HANDOFF_UNAVAILABLE] call_id=%s intent=%s transfer_callback=missing",
                call_id or "GLOBAL_CALL",
                intent,
            )
            state.handoff_state = "idle"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = False
            state.transfer_requested = False
            state.transfer_executed = False
            state.phase = "QA"
            # 0605: 担当者不在→AI継続案内
            template_ids = ["0605"]
            # 代替案を提示するためのメタ情報を設定（後続フローで参照可能に）
            state.meta["handoff_unavailable"] = True
            state.meta["handoff_alternative_offered"] = True
            reply_text = self._render_templates(template_ids)
            state.last_intent = "INQUIRY"
            return reply_text, template_ids, "HANDOFF_UNAVAILABLE", False

        # 【修正】HANDOFF_REQUEST は handoff_state に関係なく、常に 0604 を返す
        # handoff_state == "done" の状態でも「担当者お願いします」と言われたら、再度確認文を返す
        # 
        # テストケース:
        # - state.phase = "AFTER_085", state.handoff_state = "done" で
        #   intent = "HANDOFF_REQUEST" が来た場合:
        #   → templates = ["0604"], handoff_state = "confirming" になることを確認
        if intent == "HANDOFF_REQUEST":
            state.handoff_state = "confirming"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = True
            state.transfer_requested = False
            state.transfer_executed = False  # 転送フラグもリセット
            # 既存の HANDOFF_REQUEST（明示的な要求）の場合は、メタ情報が設定されていない
            # 強制ハンドオフの場合は既に state.meta が設定されているので、そのまま維持
            template_ids = ["0604"]
            reply_text = self._render_templates(template_ids)
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                "HANDOFF_REQUEST",
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, "HANDOFF_REQUEST", False
        
        # HANDOFF already completed → never output 0604/104 again
        if handoff_state == "done" and not state.transfer_requested:
            template_ids, base_intent, transfer_requested = self._run_conversation_flow(call_id, raw_text)
            template_ids = [tid for tid in template_ids if tid not in ("0604", "104")]
            reply_text = self._render_templates(template_ids)
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                base_intent,
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, base_intent, transfer_requested
        
        # HANDOFF confirming → delegate to dedicated handler
        if handoff_state == "confirming":
            reply_text, template_ids, result_intent, transfer_requested = self._handle_handoff_confirm(
                call_id, raw_text, intent, state
            )
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                result_intent,
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, result_intent, transfer_requested
        
        # Not in HANDOFF yet: first UNKNOWN → propose handoff with 0604 only (once per call)
        if intent == "UNKNOWN" and handoff_state == "idle" and not state.handoff_prompt_sent:
            state.handoff_state = "confirming"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = True
            state.transfer_requested = False
            template_ids = ["0604"]
            reply_text = self._render_templates(template_ids)
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                "UNKNOWN",
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, "UNKNOWN", False
        
        # Normal QA flow
        template_ids, base_intent, transfer_requested = self._run_conversation_flow(call_id, raw_text)
        # If both 0604 and 104 are present, keep 0604 and drop 104
        # (do not speak both in the same turn)
        if "0604" in template_ids and "104" in template_ids:
            template_ids = [tid for tid in template_ids if tid != "104"]
        
        # 【フォールバック】HANDOFF_REQUEST で template_ids が空の場合は必ず 0604 を返す
        # これにより、どのフェーズでも HANDOFF_REQUEST に対して無言になることを防ぐ
        # 注意: 通常は 1376行目で HANDOFF_REQUEST を処理するが、何らかの理由で
        # _run_conversation_flow に到達した場合の保険としてここでも処理する
        if (intent == "HANDOFF_REQUEST" or base_intent == "HANDOFF_REQUEST") and not template_ids:
            self.logger.warning(
                "HANDOFF_REQUEST_FALLBACK: call_id=%s phase=%s handoff_state=%s template_ids was empty, forcing 0604",
                call_id or "GLOBAL_CALL",
                state.phase,
                state.handoff_state,
            )
            state.handoff_state = "confirming"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = True
            state.transfer_requested = False
            state.transfer_executed = False
            template_ids = ["0604"]
            base_intent = "HANDOFF_REQUEST"
            # reply_text は後で _render_templates で生成される
        
        # 【修正理由】フォールバック処理の前にストリーク処理を実行すると、
        # フォールバックで ["110"] が設定された場合にストリークが正しく動作しない
        # そのため、フォールバック処理の後にストリーク処理を実行する必要がある
        # しかし、_run_conversation_flow 内でフォールバックが実行されるため、
        # ここでストリーク処理を実行する前に、template_ids が ["110"] かどうかを確認する
        
        # 「もう一度お願いします（110）」の連発を監視して、2回目で 0604 に切り替える
        key = call_id or "GLOBAL_CALL"
        
        # not_heard_streak の処理（MisunderstandingGuard に委譲）
        template_ids, intent, should_return_early = self._mis_guard.handle_not_heard_streak(
            call_id, state, template_ids, intent, base_intent
        )
        if should_return_early:
            # 0604 に切り替えた場合、reply_text を再生成する必要がある
            reply_text = self._render_templates(template_ids)
            return reply_text, template_ids, base_intent, transfer_requested
        
        # unclear_streak の処理（MisunderstandingGuard に委譲）
        self._mis_guard.handle_unclear_streak(call_id, state, template_ids)
        
        # --- 修正版: 「質問に答えたあと」に085を追加する ---
        # ユーザー質問直後ではなく、
        # AIが質問に回答した後（回答テンプレートが選択された時）に085を追加するよう修正。
        # これにより、自然なQA対話になる。
        # 質問intent（ユーザーが質問したintent）
        question_intents = [
            "PRICE", "SYSTEM_INQUIRY", "FUNCTION", "SUPPORT",
            "AI_IDENTITY", "SYSTEM_EXPLAIN", "RESERVATION",
            "MULTI_STORE", "DIALECT", "CALLBACK_REQUEST",
            "SETUP_DIFFICULTY", "AI_CALL_TOPIC", "SETUP"
        ]
        # 回答テンプレート（質問に対する回答として使われるテンプレートID）
        answer_templates = [
            "040", "041", "042", "043", "044", "045", "046", "047", "048", "049",  # 料金関連
            "020", "021", "022", "023", "023_AI_IDENTITY", "024", "025", "026",  # システム関連
            "060", "061", "062", "063", "064", "065", "066", "067", "068", "069",  # 機能・設定関連
            "070", "071", "072",  # 予約関連
            "0600", "0601", "0603",  # その他回答テンプレート
            "0280", "0281", "0282", "0283", "0284", "0285",  # 導入実績・サポート関連
        ]
        
        # 質問intentで、回答テンプレートが選択されている場合に085を追加
        if (base_intent in question_intents
            and "085" not in template_ids
            and state.phase != "AFTER_085"
            and base_intent not in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO", "END_CALL")
            and template_ids
            and any(tid in answer_templates for tid in template_ids)):
            # 回答テンプレートの直後にフォローアップとして085を出す
            template_ids.append("085")
            state.phase = "AFTER_085"
            self.logger.debug(
                "[NLG_DEBUG] Added 085 after answer intent: call_id=%s intent=%s tpl=%s phase=%s",
                call_id or "GLOBAL_CALL",
                base_intent,
                template_ids,
                state.phase,
            )
        
        reply_text = self._render_templates(template_ids)
        
        # ★ 086/087 を選んだ時点で必ず自動切断予約（転送しない場合のクローズ用）
        if "086" in template_ids and "087" in template_ids:
            if self.hangup_callback:
                # 強制テスト用: 環境変数で即座に切断をテストできる
                force_immediate_hangup = os.getenv("LC_FORCE_IMMEDIATE_HANGUP", "0") == "1"
                if force_immediate_hangup:
                    # タイマーを使わず、即座に hangup_callback を呼ぶ（デバッグ用）
                    self.logger.info(
                        "DEBUG_FORCE_HANGUP: call_id=%s (immediate, no timer)",
                        key,
                    )
                    try:
                        self.hangup_callback(key)
                    except Exception as e:
                        self.logger.exception(
                            "DEBUG_FORCE_HANGUP_ERROR: call_id=%s error=%r",
                            key, e
                        )
                else:
                    # 通常モード: 60秒後に自動切断
                    self.logger.info(
                        "AUTO_HANGUP_DIRECT_SCHEDULE: call_id=%s delay=60.0",
                        key,
                    )
                    try:
                        self._schedule_auto_hangup(key, delay_sec=60.0)
                    except Exception as e:
                        self.logger.exception(
                            "AUTO_HANGUP_DIRECT_SCHEDULE_ERROR: call_id=%s error=%r",
                            key, e
                        )
            else:
                self.logger.warning(
                    "AUTO_HANGUP_DIRECT_SKIP: call_id=%s reason=no_hangup_callback",
                    key,
                )
        
        # 【追加】最終決定直前のログ（DEBUGレベルに変更）
        self.logger.debug(
            "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
            call_id or "GLOBAL_CALL",
            intent,
            base_intent,
            template_ids,
            state.phase,
            state.handoff_state,
            state.not_heard_streak,
        )
        
        # GENERATE_REPLY_EXIT ログ（_generate_reply の出口を確認用）
        self.logger.info(
            "GENERATE_REPLY_EXIT: call_id=%s intent=%s base_intent=%s tpl=%s phase=%s has_086_087=%s",
            call_id or "GLOBAL_CALL",
            intent,
            base_intent,
            template_ids,
            state.phase,
            "086" in template_ids and "087" in template_ids,
        )
        
        return reply_text, template_ids, base_intent, transfer_requested

    def process_dialogue(self, pcm16k_bytes):
        # 0. WAV保存（デバッグ用、Whisperに渡す直前の音声を保存）
        if not self._wav_saved:  # 1通話あたり最初の1回だけ保存
            self._save_debug_wav(pcm16k_bytes)
        
        # 1. 音声認識 (ASR)
        text = self.asr_model.transcribe_pcm16(pcm16k_bytes)  # type: ignore[union-attr]
        self.logger.info(f"ASR Result: '{text}'")

        # ★幻聴フィルター
        if self._is_hallucination(text):
            self.logger.debug(">> Ignored hallucination (noise)")
            # ログ用に text と 'IGNORE' を返す
            return None, False, text, "IGNORE", ""
        state_key = self.call_id or "BATCH_CALL"
        resp_text, template_ids, intent, transfer_requested = self._generate_reply(state_key, text)
        self.logger.info(
            "CONV_FLOW_BATCH: call_id=%s phase=%s intent=%s templates=%s",
            state_key,
            self._get_session_state(state_key).phase,
            intent,
            template_ids,
        )
        if transfer_requested:
            self._trigger_transfer(state_key)
        should_transfer = transfer_requested

        # 4. 音声合成 (TTS) - template_ids ベースで合成
        tts_audio = None
        if template_ids and self.tts_client:
            tts_audio = self._synthesize_template_sequence(template_ids)
            if not tts_audio:
                self.logger.debug("TTS synthesis failed for template_ids=%s", template_ids)
        elif not resp_text:
            self.logger.debug("No response text generated; skipping TTS synthesis.")
        else:
            self.logger.debug("TTS クライアント未初期化のため音声合成をスキップしました。")
        
        # 音声データ, 転送フラグ, テキスト, 意図 の4つを返す
        return tts_audio, should_transfer, text, intent, resp_text

    def on_new_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        """
        ストリーミングモード: 新しい音声チャンクをASRにfeedする。
        
        :param call_id: 通話ID
        :param pcm16k_bytes: 16kHz PCM音声データ
        """
        if not self.streaming_enabled:
            return
        
        # GoogleASR の場合は feed_audio を呼び出す（feed_audio 内で最初のチャンクを first_chunk として start_stream に渡す）
        if self.asr_provider == "google":
            self.logger.debug(f"AICore: on_new_audio (provider=google) call_id={call_id} len={len(pcm16k_bytes)} bytes")
            
            # feed_audio を呼び出す（feed_audio 内でストリームが開始されていない場合は、このチャンクを first_chunk として start_stream に渡す）
            try:
                self.logger.debug(f"AICore: GoogleASR.feed_audio を呼び出し (call_id={call_id}, len={len(pcm16k_bytes)})")
                self.asr_model.feed_audio(call_id, pcm16k_bytes)  # type: ignore[union-attr]
            except Exception as e:
                self.logger.error(f"AICore: GoogleASR.feed_audio 失敗 (call_id={call_id}): {e}", exc_info=True)
                self.logger.info(f"ASR_GOOGLE_ERROR: feed_audio失敗 (call_id={call_id}): {e}")
        else:
            # Whisper の場合
            self.asr_model.feed(call_id, pcm16k_bytes)  # type: ignore[union-attr]

    def _on_asr_error(self, call_id: str, error: Exception) -> None:
        """
        GoogleASR がストリームエラー（Audio Timeout など）を起こしたときに呼ばれる。
        無音で終わらないように、フォールバック発話＋必要なら担当者ハンドオフに寄せる。
        
        :param call_id: 通話ID
        :param error: エラーオブジェクト（エラータイプによって処理を変える可能性がある）
        
        注意:
        - Audio Timeout などの一時的なエラー: フォールバック発話 + ハンドオフ
        - 認証エラーなどの永続的なエラー: ログのみ（フォールバック発話は出さない）
        - tts_callback が未設定の場合: 転送のみ実行（発話なし）
        """
        error_type = type(error).__name__
        error_msg = str(error)
        self.logger.warning(
            f"ASR_ERROR_HANDLER: call_id={call_id} error_type={error_type} error={error_msg!r}"
        )
        key = call_id or "GLOBAL_CALL"
        state = self._get_session_state(call_id)
        
        # すでにハンドオフ完了状態（担当者への転送フローを出し終わっている）なら何もしない
        # ※この場合だけ「二重に転送案内をしゃべらない」ようにする
        if state.handoff_state == "done" and state.transfer_requested:
            self.logger.info(f"ASR_ERROR_HANDLER: handoff already done (call_id={call_id})")
            return
        
        # 認証エラーなどの永続的なエラーの場合は、フォールバック発話を出さない
        # （ユーザーに誤解を与えないため）
        is_permanent_error = any(keyword in error_msg.lower() for keyword in [
            "credentials", "authentication", "permission", "unauthorized",
            "forbidden", "not found", "invalid"
        ])
        
        if is_permanent_error:
            self.logger.error(
                f"ASR_ERROR_HANDLER: permanent error detected (call_id={call_id}), "
                f"skipping fallback speech. Error: {error_msg}"
            )
            # 永続的なエラーの場合は転送も実行しない（システムエラーとして扱う）
            return
        
        # フォールバック文言（テンプレではなく生テキストで OK）
        fallback_text = "恐れ入ります。うまくお話をお伺いできませんでしたので、担当者におつなぎいたします。"
        
        # 状態を「転送要求あり」にしておく
        state.handoff_state = "done"
        state.handoff_retry_count = 0
        state.handoff_prompt_sent = True
        state.transfer_requested = True
        self._trigger_transfer_if_needed(call_id, state)
        state.last_intent = "HANDOFF_ERROR_FALLBACK"
        
        # gateway 側に「転送前の一言」として渡す
        # 注意: tts_callback が未設定の場合でも転送は実行される（発話なし）
        if hasattr(self, "tts_callback") and self.tts_callback:  # type: ignore[attr-defined]
            try:
                # 081/082 に合わせたニュアンスなので template_ids は ["081", "082"] にしておく
                template_ids = ["081", "082"]
                self.tts_callback(call_id, fallback_text, template_ids, True)  # type: ignore[misc, attr-defined]
                self.logger.info(
                    f"ASR_ERROR_HANDLER: TTS fallback sent (call_id={call_id}, text={fallback_text})"
                )
            except Exception as e:
                self.logger.exception(f"ASR_ERROR_HANDLER: tts_callback error (call_id={call_id}): {e}")
        else:
            self.logger.warning(
                f"ASR_ERROR_HANDLER: tts_callback not set (call_id={call_id}), "
                f"transfer will proceed without fallback speech"
            )

    def on_transcript(self, call_id: str, text: str, is_final: bool = True, **kwargs) -> Optional[str]:
        """
        ストリーミングモード: 確定した発話テキストを受け取り、AIロジックを実行して返答を生成する
        
        :param call_id: 通話ID
        :param text: 認識されたテキスト
        :param is_final: 確定した発話かどうか（デフォルト: True）
        :return: 返答テキスト（TTS に渡す）
        
        重要: partial（is_final=False）の場合は partial_transcripts に追記するだけ。
        会話ロジック（intent判定、テンプレート選択、ログ書き込みなど）は final（is_final=True）のときだけ実行される。
        """
        # 【追加】入口ログ（DEBUGレベルに変更）
        self.logger.debug(
            "[ASR_DEBUG] on_transcript call_id=%s is_final=%s text=%r kwargs=%r",
            call_id,
            is_final,
            text,
            kwargs,
        )
        
        self.logger.info(f"AI_CORE: on_transcript: call_id={call_id} text={text} is_final={is_final}")
        
        # call_id を self.call_id に保存（_append_call_log で使用）
        self.call_id = call_id
        
        # ============================================================
        # partial（is_final=False）の場合は partial_transcripts に追記するだけ
        # ============================================================
        # 古いpartial transcriptsをクリーンアップ（定期的に実行）
        self._cleanup_stale_partials(max_age_sec=30.0)
        
        if not is_final:
            # partial_transcripts を初期化（存在しない場合）
            if call_id not in self.partial_transcripts:
                self.partial_transcripts[call_id] = {"text": "", "updated": time.time()}
            
            # partial テキストを更新
            if text:
                # Google ASR の partial は通常、前の partial を含む形で返ってくるため、
                # 単純に最新のtextで置き換えるだけで良い（連結不要）
                # 例: "もし" → "もしもし" → "もしもしホーム"
                # ただし、非累積的なケースも検出してログに記録
                prev_text = self.partial_transcripts[call_id].get("text", "")
                if prev_text and not text.startswith(prev_text) and prev_text not in text:
                    self.logger.warning(
                        f"[ASR_PARTIAL_NON_CUMULATIVE] call_id={call_id} "
                        f"prev={prev_text!r} new={text!r} (new does not start with prev)"
                    )
                self.partial_transcripts[call_id]["text"] = text
                self.partial_transcripts[call_id]["updated"] = time.time()
            
            # デバッグログ（DEBUGレベルに変更）
            merged_text = self.partial_transcripts[call_id]["text"]
            self.logger.debug(
                "[ASR_PARTIAL] call_id=%s partial=%r",
                call_id,
                merged_text,
            )
            
            # ChatGPT音声風: 短い部分認識をトリガーに即応答（バックチャネル）
            text_stripped = text.strip() if text else ""
            if 1 <= len(text_stripped) <= 6:
                backchannel_keywords = ["はい", "えっと", "あの", "ええ", "そう", "うん", "ああ"]
                if any(keyword in text_stripped for keyword in backchannel_keywords):
                    self.logger.debug(f"[BACKCHANNEL_TRIGGER] Detected short utterance: {text_stripped}")
                    # tts_callback が設定されている場合のみ実行
                    if hasattr(self, 'tts_callback') and self.tts_callback:  # type: ignore[attr-defined]
                        try:
                            self.tts_callback(call_id, "はい", None, False)  # type: ignore[misc, attr-defined]
                            self.logger.info(f"[BACKCHANNEL_SENT] call_id={call_id} text='はい' (triggered by partial: {text_stripped!r})")
                        except Exception as e:
                            self.logger.exception(f"[BACKCHANNEL_ERROR] call_id={call_id} error={e}")
            
            # partial の場合は会話ロジックを実行しない
            return None
        
        # ============================================================
        # ここから下は final（is_final=True）のときだけ実行される
        # ============================================================
        
        # 過去の partial を取り出す
        partial_text = ""
        if call_id in self.partial_transcripts:
            partial_text = self.partial_transcripts[call_id].get("text", "")
            # partial_transcripts をクリア
            del self.partial_transcripts[call_id]
        
        # Google ASR の final は通常、全ての partial を含むため、
        # final が空でない限り final を使用
        merged_text = text if text else partial_text
        
        self.logger.info(
            f"[ASR_FINAL] call_id={call_id} "
            f"partial={partial_text!r} final={text!r} merged={merged_text!r}"
        )
        
        # 最小長チェック（2文字以上で処理）
        # ただし、1文字の曖昧な発話（「あ」「ん」「え」「お」）は NOT_HEARD として処理
        if len(merged_text) < MIN_TEXT_LENGTH_FOR_INTENT:
            if len(merged_text) == 1:
                ambiguous_chars = ["あ", "ん", "え", "お", "う", "い"]
                if merged_text in ambiguous_chars:
                    self.logger.debug(
                        f"[ASR_AMBIGUOUS] call_id={call_id} text={merged_text!r} -> treating as NOT_HEARD"
                    )
                    # NOT_HEARD として処理（110を返す）
                    intent = "NOT_HEARD"
                    template_ids = ["110"]
                    reply_text = self._render_templates(template_ids)
                    # TTS コールバック
                    if hasattr(self, 'tts_callback') and self.tts_callback:  # type: ignore[attr-defined]
                        try:
                            self.tts_callback(call_id, reply_text, template_ids, False)  # type: ignore[misc, attr-defined]
                            self.logger.info(
                                f"TTS_SENT: call_id={call_id} templates={template_ids} (NOT_HEARD for ambiguous 1-char)"
                            )
                        except Exception as e:
                            self.logger.exception(f"TTS_ERROR: call_id={call_id} error={e}")
                    return reply_text
            # それ以外の短い発話はスキップ
            self.logger.debug(
                f"[ASR_SHORT] call_id={call_id} text={merged_text!r} "
                f"len={len(merged_text)} -> skipping (too short)"
            )
            return None
        
        # ユーザー発話（確定）をログに記録（merged_text を使用）
        if merged_text:
            try:
                self._append_call_log("USER", merged_text)
            except Exception as e:
                # ログ記録の失敗は通話処理を止めない
                self.logger.exception("CALL_LOGGING_ERROR (USER): %s", e)
            
            # ユーザー発話時にno_input_streakをリセット
            state = self._get_session_state(call_id)
            if state.no_input_streak > 0:
                self.logger.info(
                    f"[NO_INPUT] call_id={call_id} streak reset (user input: {merged_text[:20]!r}...)"
                )
                state.no_input_streak = 0
        
        if not merged_text:
            return None
        
        # 幻聴フィルター（merged_text を使用）
        if self._is_hallucination(merged_text):
            self.logger.debug(">> Ignored hallucination (noise)")
            return None
        
        # 【追加】intent 判定直前のログ（DEBUGレベルに変更）
        self.logger.debug(
            "[ASR_DEBUG] merged_for_intent call_id=%s text=%r",
            call_id,
            merged_text,
        )
        
        # 会話フロー処理（intent判定、テンプレート選択など）（merged_text を使用）
        state = self._get_session_state(call_id)
        phase_before = state.phase
        
        # 空のテキスト（無音検出時）の場合は、no_input_streakに基づいてテンプレートを選択
        if not merged_text or len(merged_text.strip()) == 0:
            # 無音検出時の処理
            no_input_streak = state.no_input_streak
            self.logger.info(
                f"[NO_INPUT] call_id={call_id} streak={no_input_streak} (empty text detected)"
            )
            
            if no_input_streak == 1:
                template_ids = ["110"]
            elif no_input_streak == 2:
                template_ids = ["111"]
            else:
                template_ids = ["112"]
                # テンプレート112の場合は自動切断を予約
                if self.hangup_callback:
                    self.logger.info(
                        f"[NO_INPUT] call_id={call_id} template=112, scheduling auto_hangup delay=2.0s"
                    )
                    try:
                        self._schedule_auto_hangup(call_id, delay_sec=2.0)
                    except Exception as e:
                        self.logger.exception(
                            f"[NO_INPUT] AUTO_HANGUP_SCHEDULE_ERROR: call_id={call_id} error={e!r}"
                        )
            
            reply_text = self._render_templates(template_ids)
            intent = "NOT_HEARD"
            transfer_requested = False
            
            # last_ai_templatesを設定（TTS送信用）
            state.last_ai_templates = template_ids
            
            # ログ出力（発信者番号を含む）
            caller_number = getattr(self, "caller_number", None) or "未設定"
            self.logger.info(
                f"[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} template={template_ids[0] if template_ids else 'NONE'}"
            )
        else:
            # 通常の処理（ユーザー発話あり）
            reply_text, template_ids, intent, transfer_requested = self._generate_reply(call_id, merged_text)
        
        # 状態取得（一度だけ）
        phase_after = state.phase
        
        self.logger.info(
            f"CONV_FLOW: call_id={call_id} "
            f"phase={phase_before}->{phase_after} intent={intent} "
            f"templates={template_ids} transfer={transfer_requested}"
        )

        # END 遷移時の自動切断（転送しない場合のみ）
        if phase_before != "END" and phase_after == "END" and not state.transfer_requested:
            self.logger.info(
                f"AUTO_HANGUP: scheduling for call_id={call_id}"
            )
            self._schedule_auto_hangup(call_id, delay_sec=60.0)

        # AI応答をログ記録
        self._log_ai_templates(template_ids)

        if not reply_text:
            self.logger.debug("No reply generated for call_id=%s (phase=%s)", call_id, phase_after)
            # 転送要求があるが返答テキストがない場合でも転送処理を実行
            if transfer_requested:
                self._trigger_transfer_if_needed(call_id, state)
            return None
        
        # 【改善1】INTROフェーズ中はENTRYテンプレート送信を抑制（intro再生中の被り防止）
        # 注意: ログ、state更新、会話フロー処理は通常通り実行し、TTS送信だけを抑制
        # 【修正1】state.phase を直接参照（phase_after はフロー処理後に更新されている可能性があるため）
        current_phase = state.phase
        if current_phase == "INTRO":
            self.logger.debug(
                f"[AICORE] Phase=INTRO, skipping TTS (intro playing) call_id={call_id} "
                f"templates={template_ids} (other processing completed)"
            )
            # TTS送信は抑制するが、転送処理は実行（転送要求がある場合）
            # 【修正3】_trigger_transfer_if_needed() は転送処理のみ（TTS送信はしない）前提
            if transfer_requested:
                self._trigger_transfer_if_needed(call_id, state)
            # 【修正2】返り値はログ用のみ（呼び出し側で別チャネル送信はしない前提）
            return reply_text  # ログ記録などのために返答テキストは返す
        
        # TTS コールバック（転送要求フラグも渡す）
        # 注意: transfer_requested=True の場合、_send_tts 内でTTS送信完了後に転送処理が開始される
        if hasattr(self, 'tts_callback') and self.tts_callback:  # type: ignore[attr-defined]
            try:
                self.tts_callback(call_id, reply_text, template_ids, transfer_requested)  # type: ignore[misc, attr-defined]
                self.logger.info(
                    f"TTS_SENT: call_id={call_id} templates={template_ids} transfer_requested={transfer_requested}"
                )
            except Exception as e:
                self.logger.exception(f"TTS_ERROR: call_id={call_id} error={e}")
        
        # 転送処理は _send_tts 内でTTS送信完了後に実行されるため、ここでは実行しない
        # （transfer_requested=True の場合、_send_tts 内で _wait_for_tts_and_transfer が起動される）
        
        return reply_text
    
    def _log_ai_templates(self, template_ids: List[str]) -> None:
        """AI応答のログ記録を分離"""
        try:
            from .intent_rules import TEMPLATE_CONFIG
            for tid in template_ids:
                cfg = TEMPLATE_CONFIG.get(tid)
                if cfg and cfg.get("text"):
                    self._append_call_log("AI", cfg["text"], template_id=tid)
        except Exception as e:
            self.logger.exception(f"CALL_LOGGING_ERROR (AI): {e}")
    
    def _cleanup_stale_partials(self, max_age_sec: float = 30.0) -> None:
        """
        古いpartial transcriptsをクリーンアップ
        
        :param max_age_sec: 最大保持時間（秒）。デフォルト: 30秒
        """
        now = time.time()
        stale_keys = [
            call_id for call_id, data in self.partial_transcripts.items()
            if now - data.get("updated", 0) > max_age_sec
        ]
        for key in stale_keys:
            self.logger.warning(
                f"PARTIAL_CLEANUP: removing stale partial for call_id={key} "
                f"(age={now - self.partial_transcripts[key].get('updated', 0):.1f}s)"
            )
            del self.partial_transcripts[key]
    
    def check_for_transcript(self, call_id: str) -> Optional[Tuple[str, float, float, float]]:
        """
        ストリーミングモード: 確定した発話があればテキストを返す。
        
        :param call_id: 通話ID
        :return: (text, audio_duration_sec, inference_time_sec, end_to_text_delay_sec) または None
        """
        if not self.streaming_enabled:
            return None
        
        result = self.asr_model.poll_result(call_id)  # type: ignore[union-attr]
        if result is None:
            return None
        
        # poll_resultは既に (text, audio_duration, inference_time, end_to_text_delay) を返す
        return result

    def _schedule_auto_hangup(self, call_id: str, delay_sec: float = 2.0) -> None:
        """
        自動切断をスケジュールする（無音タイムアウト時など）
        
        :param call_id: 通話ID
        :param delay_sec: 切断までの遅延時間（秒）
        """
        if not self.hangup_callback:
            self.logger.warning(
                f"[AUTO_HANGUP] call_id={call_id} hangup_callback not set, cannot schedule hangup"
            )
            return
        
        key = call_id or "GLOBAL_CALL"
        
        # 既存のタイマーがあればキャンセル
        if key in self._auto_hangup_timers:
            old_timer = self._auto_hangup_timers.pop(key)
            try:
                old_timer.cancel()
                self.logger.debug(f"[AUTO_HANGUP] canceled existing timer for call_id={call_id}")
            except Exception as e:
                self.logger.warning(f"[AUTO_HANGUP] failed to cancel old timer: {e}")
        
        # 新しいタイマーをスケジュール
        def do_hangup():
            try:
                self.logger.info(
                    f"[AUTO_HANGUP] executing hangup for call_id={call_id} after {delay_sec}s delay"
                )
                if self.hangup_callback:
                    self.hangup_callback(call_id)
                    self.logger.info(f"[AUTO_HANGUP] hangup_callback executed for call_id={call_id}")
                else:
                    self.logger.error(f"[AUTO_HANGUP] hangup_callback was None when timer fired for call_id={call_id}")
            except Exception as e:
                self.logger.exception(f"[AUTO_HANGUP] error executing hangup for call_id={call_id}: {e}")
            finally:
                # タイマーを辞書から削除
                self._auto_hangup_timers.pop(key, None)
        
        timer = threading.Timer(delay_sec, do_hangup)
        timer.daemon = True
        timer.start()
        self._auto_hangup_timers[key] = timer
        
        self.logger.info(
            f"[AUTO_HANGUP] scheduled hangup for call_id={call_id} delay={delay_sec}s"
        )
    
    def reset_call(self, call_id: str) -> None:
        """
        ストリーミングモード: call_idの状態をリセット（通話終了時など）。
        
        :param call_id: 通話ID
        """
        if self.streaming_enabled and self.asr_model is not None:
            # GoogleASR の場合は end_stream を呼び出す
            if self.asr_provider == "google":
                try:
                    self.asr_model.end_stream(call_id)  # type: ignore[union-attr]
                except Exception as e:
                    self.logger.warning(f"AICore: GoogleASR ストリーム終了エラー (call_id={call_id}): {e}")
            self.asr_model.reset_call(call_id)  # type: ignore[union-attr]
        self._reset_session_state(call_id)
        # 【追加】partial_transcripts もクリア
        if call_id in self.partial_transcripts:
            del self.partial_transcripts[call_id]
        # AUTO HANGUP TIMER もクリア
        # 注意: _schedule_auto_hangup でも既存タイマーをキャンセルしているが、
        # reset_call では通話終了時のクリーンアップとして実行する
        key = call_id or "GLOBAL_CALL"
        timer = self._auto_hangup_timers.pop(key, None)
        if timer is not None:
            try:
                timer.cancel()
                self.logger.info(
                    "AUTO_HANGUP_TIMER_CANCELED: call_id=%s", key
                )
            except Exception as e:
                self.logger.warning(
                    "AUTO_HANGUP_TIMER_CANCEL_ERROR: call_id=%s error=%r",
                    key, e
                )