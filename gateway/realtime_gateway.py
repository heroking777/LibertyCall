#!/usr/bin/env python3
"""
README (dev tips):
    本番 Gateway (UDP 7000) を止めずに開発用でログを確認する場合:
        export LC_GATEWAY_PORT=7001
        ./venv/bin/python libertycall/gateway/realtime_gateway.py
    これで Whisper / VAD / 推論ログが前面に流れます。
"""
import asyncio
import logging
import signal
import struct
import sys
import json
import os
import subprocess
import wave
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict
import yaml
import websockets
import audioop
import collections
import time
try:
    from webrtc_audio_processing import AudioProcessing, NsLevel
    WEBRTC_NS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    WEBRTC_NS_AVAILABLE = False
    AudioProcessing = None
    NsLevel = None

# --- プロジェクトルートを sys.path に追加 ---
_CURRENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CURRENT_DIR.parent         # /opt/libertycall
_REPO_PARENT = _PROJECT_ROOT.parent         # /opt
if str(_REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(_REPO_PARENT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# --- モジュール読み込み ---
from libertycall.client_loader import load_client_profile
from libertycall.gateway.ai_core import AICore
from libertycall.gateway.audio_utils import ulaw8k_to_pcm16k, pcm24k_to_ulaw8k
from libertycall.gateway.intent_rules import normalize_text
from libertycall.gateway.transcript_normalizer import normalize_transcript
from libertycall.console_bridge import console_bridge
from google.cloud import texttospeech

# デバッグ用: AICore のインポート元を確認
logger_debug = logging.getLogger("libertycall.gateway.ai_core")
logger_debug.warning("DEBUG_IMPORT_CHECK: AICore class from %r", AICore.__module__)
logger_debug.warning("DEBUG_IMPORT_CHECK_FILE: ai_core file = %r", AICore.__init__.__code__.co_filename)
try:
    from .audio_manager import AudioManager
except ImportError:  # 実行形式(py gateway/realtime_gateway.py)との両立
    from audio_manager import AudioManager  # type: ignore

# ★ 転送先電話番号 (デフォルト)
OPERATOR_NUMBER = "08024152649"

class RTPPacketBuilder:
    RTP_VERSION = 2
    def __init__(self, payload_type: int, sample_rate: int, ssrc: Optional[int] = None):
        self.payload_type = payload_type
        self.sample_rate = sample_rate
        self.ssrc = ssrc or self._generate_ssrc()
        self.sequence_number = 0
        self.timestamp = 0

    def _generate_ssrc(self) -> int:
        import random
        return random.randint(0, 0xFFFFFFFF)

    def build_packet(self, payload: bytes) -> bytes:
        header = bytearray(12)
        header[0] = (self.RTP_VERSION << 6)
        header[1] = self.payload_type & 0x7F
        struct.pack_into('>H', header, 2, self.sequence_number)
        struct.pack_into('>I', header, 4, self.timestamp)
        struct.pack_into('>I', header, 8, self.ssrc)
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        samples = len(payload) // 2 
        self.timestamp = (self.timestamp + samples) & 0xFFFFFFFF
        return bytes(header) + payload

class RealtimeGateway:
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.rtp_host = config["rtp"]["listen_host"]
        # ポート番号の優先順位: LC_RTP_PORT > LC_GATEWAY_PORT > gateway.yaml > 固定値 7100
        # LC_RTP_PORT を優先（新規環境変数）
        env_port = os.getenv("LC_RTP_PORT") or os.getenv("LC_GATEWAY_PORT")
        if env_port:
            try:
                self.rtp_port = int(env_port)
                env_name = "LC_RTP_PORT" if os.getenv("LC_RTP_PORT") else "LC_GATEWAY_PORT"
                self.logger.debug(f"{env_name} override detected: {self.rtp_port}")
            except ValueError:
                self.logger.warning("LC_RTP_PORT/LC_GATEWAY_PORT is invalid (%s). Falling back to config file.", env_port)
                # 環境変数が無効な場合は config ファイルの値を試す
                self.rtp_port = config["rtp"].get("listen_port", 7100)
        else:
            # 環境変数が無い場合は config ファイルの値を使用
            self.rtp_port = config["rtp"].get("listen_port", 7100)
        self.payload_type = config["rtp"]["payload_type"]
        self.sample_rate = config["rtp"]["sample_rate"]
        self.ws_url = config["ws"]["url"]
        self.reconnect_delay = config["ws"]["reconnect_delay_sec"]

        self.rtp_peer: Optional[Tuple[str, int]] = None
        self.websocket = None
        self.rtp_transport = None
        self.rtp_builder: Optional[RTPPacketBuilder] = None
        self.running = False
        self.shutdown_event = asyncio.Event()

        # --- AI & 音声制御用パラメータ ---
        self.logger.debug("Initializing AI Core...")
        self.ai_core = AICore()
        # TTS 送信用コールバックを設定
        self.ai_core.tts_callback = self._send_tts
        self.ai_core.transfer_callback = self._handle_transfer
        # 自動切断用コールバックを設定
        self.ai_core.hangup_callback = self._handle_hangup
        self.logger.info(
            "HANGUP_CALLBACK_SET: hangup_callback=%s",
            "set" if self.ai_core.hangup_callback else "none"
        )
        
        # ストリーミングモード判定
        self.streaming_enabled = os.getenv("LC_ASR_STREAMING_ENABLED", "0") == "1"
        
        # ASR プロバイダに応じたログ出力
        asr_provider = getattr(self.ai_core, 'asr_provider', 'google')
        if asr_provider == "whisper" and self.streaming_enabled:
            model_name = os.getenv("LC_ASR_WHISPER_MODEL", "base")
            chunk_ms = os.getenv("LC_ASR_CHUNK_MS", "1000")
            silence_ms = os.getenv("LC_ASR_SILENCE_MS", "700")
            self.logger.info(
                f"Streaming ASR モードで起動 (model={model_name}, chunk={chunk_ms}ms, silence={silence_ms}ms)"
            )
        elif asr_provider == "google" and self.streaming_enabled:
            self.logger.info("Streaming ASR モードで起動 (provider=google)")
        else:
            self.logger.info("Batch ASR モードで起動")
        
        # 起動時ログ（ASR_BOOT）は AICore の初期化時に出力されるため、ここでは削除
        
        # WebRTC Noise Suppressor初期化（利用可能な場合）
        if WEBRTC_NS_AVAILABLE:
            self.ns = AudioProcessing(ns_level=NsLevel.HIGH)
            self.logger.debug("WebRTC Noise Suppressor enabled")
        else:
            self.ns = None
            self.logger.warning("WebRTC Noise Suppressor not available, skipping NS processing")
        
        self.audio_buffer = bytearray()          
        self.tts_queue = collections.deque(maxlen=100)  # バッファ拡張（音途切れ防止）
        self.is_speaking_tts = False             
        self.last_voice_time = time.time()
        self.is_user_speaking = False
        
        # 転送処理の遅延実行用
        self._pending_transfer_call_id: Optional[str] = None  # 転送待ちのcall_id
        self._transfer_task_queue = collections.deque()  # イベントループが起動する前の転送タスクキュー 
        
        # 調整パラメータ
        self.BARGE_IN_THRESHOLD = 1000 
        self.SILENCE_DURATION = 0.9     # 無音判定 (0.8 -> 0.9)
        self.MAX_SEGMENT_SEC = 2.3      # ★ 最大セグメント長
        self.MIN_AUDIO_LEN = 16000
        self.MIN_RMS_FOR_ASR = 80      # ★ RMS閾値（これ以下のセグメントはASRに送らない）
        self.NO_INPUT_TIMEOUT = 5.0     # 無音5秒で再促し
        self.NO_INPUT_STREAK_LIMIT = 4  # 無音ストリーク上限
        self.MAX_NO_INPUT_TIME = 60.0   # 無音の累積上限（秒）※1分で強制切断を検討
        self.SILENCE_WARNING_INTERVALS = [5.0, 10.0, 15.0]  # 無音警告を送る秒数（5秒、10秒、15秒）
        self.SILENCE_HANGUP_TIME = 20.0  # 無音20秒で自動切断
        self.NO_INPUT_SILENT_PHRASES = {"すみません", "ええと", "あの"}  # 無音扱いでリセットするフィラー
        
        # ============================================================
        # 【既存バッファリング仕様（非ストリーミングモード）】
        # ============================================================
        # 現状の実装では、以下の条件で音声をためてから一括ASRを実行：
        # 1. audio_buffer に 16kHz PCM を蓄積（handle_rtp_packet 内で extend）
        # 2. 無音が SILENCE_DURATION (0.9秒) 続いたら should_cut=True
        # 3. または、話し始めてから MAX_SEGMENT_SEC (2.3秒) 経過したら強制カット
        # 4. should_cut が True になった時点で、audio_buffer 全体を
        #    AICore.process_dialogue() に渡して一括 transcribe
        # 
        # 結果として：
        # - 短い発話（1秒）でも、無音判定待ちで 0.9秒 + 推論 0.5秒 = 1.4秒遅延
        # - 長い発話（2秒）でも、MAX_SEGMENT_SEC 待ちで 2.3秒 + 推論 0.5秒 = 2.8秒遅延
        # - ログ上「audio=2.3〜3.0秒 / infer≈0.5〜0.6秒」となる理由は上記の通り
        # 
        # ストリーミングモード（LC_ASR_STREAMING_ENABLED=1）では、
        # この「2〜3秒ためる方式」を廃止し、小さいチャンク単位でASRを実行する。
        # ============================================================      
        
        # ★ セグメント開始時刻管理
        self.current_segment_start = None
        # -------------------------------------

        # ログ用変数
        # turn_id: ユーザー発話の通し番号（ストリーミング/非ストリーミングモード共通で使用）
        self.turn_id = 1
        self.turn_rms_values = []
        
        # ユーザー発話のturn_index管理（補正用）
        self.user_turn_index = 0  # ユーザー発話のカウンター（1始まり）
        self.call_start_time = None  # 通話開始時刻
        
        # RTP受信ログ用カウンター（50パケットに1回だけINFO）
        self.rtp_packet_count = 0
        self.last_rtp_packet_time = 0.0
        self.RTP_PEER_IDLE_TIMEOUT = float(os.getenv("LC_RTP_PEER_IDLE_TIMEOUT", "2.0"))
        
        # クライアントプロファイル管理
        self.client_id = None
        self.client_profile = None
        self.rules = None
        self.console_bridge = console_bridge
        self.audio_manager = AudioManager(_PROJECT_ROOT)
        self.default_client_id = os.getenv("LC_DEFAULT_CLIENT_ID", "000")
        self.initial_sequence_played = False
        self.initial_sequence_playing = False  # 初回シーケンス再生中フラグ
        self.initial_silence_sec = 0.5
        self.call_id: Optional[str] = None
        self.current_state = "init"
        
        # 音量レベル送信用
        self.last_audio_level_sent = 0.0
        self.last_audio_level_time = 0.0
        self.AUDIO_LEVEL_INTERVAL = 0.2  # 200ms間隔（5Hz）
        self.AUDIO_LEVEL_THRESHOLD = 0.05  # レベル変化が5%未満なら送らない
        self.RMS_MAX = 32767.0  # 16bit PCMの最大値（正規化用）
        self.recent_dialogue = collections.deque(maxlen=8)
        self.transfer_notified = False
        self.call_completed = False
        
        # ストリーミングモード用変数を事前に初期化
        self._stream_chunk_counter = 0
        self._last_feed_time = time.time()
        
        # 無音検出用変数
        self._last_user_input_time: Dict[str, float] = {}  # call_id -> 最後のユーザー発話時刻
        self._last_tts_end_time: Dict[str, float] = {}  # call_id -> 最後のTTS送信完了時刻
        self._no_input_timers: Dict[str, asyncio.Task] = {}  # call_id -> 無音検出タイマータスク
        self._no_input_elapsed: Dict[str, float] = {}  # call_id -> 無音経過秒数（累積）
        self._silence_warning_sent: Dict[str, set] = {}  # call_id -> 送信済み警告秒数のセット（5, 10, 15秒）
        self._last_silence_time: Dict[str, float] = {}  # call_id -> 最後の無音フレーム検出時刻
        self._last_voice_time: Dict[str, float] = {}  # call_id -> 最後の有音フレーム検出時刻
        self._active_calls: set = set()  # アクティブな通話IDのセット
        self._initial_tts_sent: set = set()  # 初期TTS送信済みの通話IDセット
        self._last_tts_text: Optional[str] = None  # 直前のTTSテキスト（重複防止用）
        self._call_addr_map: Dict[Tuple[str, int], str] = {}  # (host, port) -> call_id のマッピング
        
        # 録音機能の初期化
        self.recording_enabled = os.getenv("LC_ENABLE_RECORDING", "0") == "1"
        self.recording_file: Optional[wave.Wave_write] = None
        self.recording_path: Optional[Path] = None
        if self.recording_enabled:
            recordings_dir = Path("/opt/libertycall/recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"録音機能が有効です。録音ファイルは {recordings_dir} に保存されます。")

    async def start(self):
        self.logger.info("[RTP_START] RealtimeGateway.start() called")
        self.running = True
        self.rtp_builder = RTPPacketBuilder(self.payload_type, self.sample_rate)

        try:
            loop = asyncio.get_running_loop()
            
            # ソケットをメンバに保持してbind（IPv4ループバック固定、GC防止）
            self.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.rtp_sock.bind(("127.0.0.1", self.rtp_port))
            self.rtp_sock.setblocking(False)  # asyncio用にノンブロッキングへ
            bound_addr = self.rtp_sock.getsockname()
            self.logger.info(f"[RTP_BIND_FINAL] Bound UDP socket to {bound_addr}")
            
            # asyncioにソケットを渡す
            self.rtp_transport, _ = await loop.create_datagram_endpoint(
                lambda: RTPProtocol(self),
                sock=self.rtp_sock
            )
            self.logger.info(f"[RTP_READY_FINAL] RTP listener active and awaiting packets on {bound_addr}")

            # WebSocketサーバー起動処理
            try:
                ws_task = asyncio.create_task(self._ws_server_loop())
                self.logger.info("[BOOT] WebSocket server startup scheduled on port 9001 (task=%r)", ws_task)
            except Exception as e:
                self.logger.error(f"[BOOT] Failed to start WebSocket server: {e}", exc_info=True)
            
            asyncio.create_task(self._ws_client_loop())
            asyncio.create_task(self._tts_sender_loop())
            
            # ストリーミングモード: 定期的にASR結果をポーリング
            if self.streaming_enabled:
                asyncio.create_task(self._streaming_poll_loop())
            
            # 無音検出ループ開始（TTS送信後の無音を監視）
            if not getattr(self, "_silence_loop_started", False):
                self.logger.info("RealtimeGateway started — scheduling silence monitor loop")
                try:
                    # イベントループが確実に起動していることを確認
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(self._no_input_monitor_loop())
                    self._silence_loop_started = True
                    self.logger.info("NO_INPUT_MONITOR_LOOP: scheduled successfully (task=%r)", task)
                except RuntimeError as e:
                    # イベントループがまだ起動していない場合（通常は発生しない）
                    self.logger.error("Event loop not running yet — cannot start silence monitor loop: %s", e)
                    # 少し遅延してから再試行（非同期で実行）
                    async def delayed_start():
                        await asyncio.sleep(1.0)
                        try:
                            loop = asyncio.get_running_loop()
                            task = loop.create_task(self._no_input_monitor_loop())
                            self._silence_loop_started = True
                            self.logger.info("NO_INPUT_MONITOR_LOOP: scheduled successfully after delay (task=%r)", task)
                        except Exception as ex:
                            self.logger.exception("Delayed silence monitor launch failed: %s", ex)
                    asyncio.create_task(delayed_start())
                    self.logger.warning("Event loop not running yet — scheduled delayed silence monitor launch")
            else:
                self.logger.warning("Silence monitor loop already started, skipping duplicate launch")
            
            # ログファイル監視ループ開始（転送失敗時のTTSアナウンス用）
            asyncio.create_task(self._log_monitor_loop())
            
            # イベントループ起動後にキューに追加された転送タスクを処理
            # 注意: イベントループが起動した後でないと asyncio.create_task が呼べない
            async def process_queued_transfers():
                while self._transfer_task_queue:
                    call_id = self._transfer_task_queue.popleft()
                    self.logger.info(f"TRANSFER_TASK_PROCESSING: call_id={call_id} (from queue)")
                    asyncio.create_task(self._wait_for_tts_and_transfer(call_id))
                # 定期的にキューをチェック（新しいタスクが追加される可能性があるため）
                while self.running:
                    await asyncio.sleep(0.5)  # 0.5秒間隔でチェック
                    while self._transfer_task_queue:
                        call_id = self._transfer_task_queue.popleft()
                        self.logger.info(f"TRANSFER_TASK_PROCESSING: call_id={call_id} (from queue, delayed)")
                        asyncio.create_task(self._wait_for_tts_and_transfer(call_id))
            
            asyncio.create_task(process_queued_transfers())

            # サービスを維持（停止イベントを待つ）
            await self.shutdown_event.wait()

        except Exception as e:
            self.logger.error(f"[RTP_BIND_ERROR_FINAL] {e}", exc_info=True)
        finally:
            if hasattr(self, "rtp_transport") and self.rtp_transport:
                self.logger.info("[RTP_EXIT_FINAL] Closing RTP transport")
                self.rtp_transport.close()
            if hasattr(self, "rtp_sock") and self.rtp_sock:
                self.rtp_sock.close()
                self.logger.info("[RTP_EXIT_FINAL] Socket closed")

    def _send_tts(self, call_id: str, reply_text: str, template_ids: list[str] | None = None, transfer_requested: bool = False) -> None:
        """
        TTS を生成してキューに追加する（AICore.on_transcript から呼び出される）
        
        :param call_id: 通話ID
        :param reply_text: 返答テキスト
        :param template_ids: テンプレIDのリスト（指定された場合は template_id ベースで TTS 合成）
        :param transfer_requested: 転送要求フラグ（True の場合はTTS送信完了後に転送処理を開始）
        """
        if not reply_text and not template_ids:
            return
        
        # 会話状態を取得（ログ出力用）
        state = self.ai_core._get_session_state(call_id)
        phase = state.phase
        template_id_str = ",".join(template_ids) if template_ids else "NONE"
        
        # 発信者番号を取得
        caller_number = getattr(self.ai_core, "caller_number", None) or "-"
        if caller_number == "-" or not caller_number:
            caller_number = "未設定"
        
        # 会話トレースログを出力（発信者番号を含む）
        log_entry = f"[{datetime.now().isoformat()}] CALLER={caller_number} PHASE={phase} TEMPLATE={template_id_str} TEXT={reply_text}"
        
        # コンソールに出力（発信者番号を表示）
        print(f"🗣️ [発信者: {caller_number}] {log_entry}")
        
        # ログファイルに追記
        conversation_log_path = Path(_PROJECT_ROOT) / "logs" / "conversation_trace.log"
        conversation_log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(conversation_log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            self.logger.warning(f"Failed to write conversation trace log: {e}")
        
        # 重複TTS防止: 直前のTTSテキストと同じ場合はキューに追加しない
        tts_text_for_check = reply_text or (",".join(template_ids) if template_ids else "")
        
        # 初回TTS（初期アナウンス）の場合は常に送信（スキップしない）
        if not self._last_tts_text:
            # 初回TTSとして記録して送信
            if tts_text_for_check:
                self._last_tts_text = tts_text_for_check
                self.logger.info(f"[PLAY_TTS] dispatching (initial) text='{tts_text_for_check[:50]}...' to TTS queue for {call_id}")
            # 初回でもテキストがない場合はここで終了
            if not tts_text_for_check:
                return
        elif tts_text_for_check and self._last_tts_text == tts_text_for_check:
            # 2回目以降の重複チェック
            self.logger.debug(f"[TTS_QUEUE_SKIP] duplicate text ignored: '{tts_text_for_check[:30]}...'")
            return
        else:
            # 新しいTTSテキストの場合
            if tts_text_for_check:
                self._last_tts_text = tts_text_for_check
        
        # TTS生成
        tts_audio_24k = None
        if template_ids and self.ai_core.tts_client:
            # template_ids ベースで TTS 合成
            tts_audio_24k = self.ai_core._synthesize_template_sequence(template_ids)
        elif reply_text and self.ai_core.tts_client and self.ai_core.voice_params and self.ai_core.audio_config:
            # 従来通り reply_text から TTS 合成（後方互換性のため）
            synthesis_input = texttospeech.SynthesisInput(text=reply_text)
            response = self.ai_core.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=self.ai_core.voice_params,
                audio_config=self.ai_core.audio_config
            )
            tts_audio_24k = response.audio_content
        
        # TTSキューに追加
        if tts_audio_24k:
            ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
            chunk_size = 160
            for i in range(0, len(ulaw_response), chunk_size):
                self.tts_queue.append(ulaw_response[i:i+chunk_size])
            self.logger.info(f"TTS_SEND: call_id={call_id} text={reply_text!r} queued={len(ulaw_response)//chunk_size} chunks")
            self.is_speaking_tts = True
            
            # TTS送信完了時刻を記録（無音検出用）
            # 実際の送信完了は_tts_sender_loopでキューが空になった時だが、
            # ここでは送信開始時刻を記録（無音検出の基準時刻として使用）
            effective_call_id = call_id or self._get_effective_call_id()
            if effective_call_id:
                # TTS送信完了を待つ非同期タスクを起動
                asyncio.create_task(self._wait_for_tts_completion_and_update_time(effective_call_id, len(ulaw_response)))
            
            # wait_time_afterの処理: テンプレート006の場合は1.8秒待機
            # 注意: 実際の待機処理は非同期で行うため、ここではフラグを設定
            if template_ids and "006" in template_ids:
                from libertycall.gateway.intent_rules import get_template_config
                template_config = get_template_config("006")
                if template_config and template_config.get("wait_time_after"):
                    wait_time = template_config.get("wait_time_after", 1.8)
                    # 非同期タスクで待機処理を実行（実際の実装は後で追加）
                    self.logger.debug(f"TTS_WAIT: template 006 sent, will wait {wait_time}s for user response")
        
        # 転送要求フラグが立っている場合、TTS送信完了後に転送処理を開始
        if transfer_requested:
            self.logger.info("Transfer requested by AI core (handoff flag received). Will start transfer after TTS completion.")
            self._pending_transfer_call_id = call_id
            # TTS送信完了を待ってから転送処理を開始する非同期タスクを作成
            # 注意: _send_ttsは同期メソッドなので、イベントループを取得してからタスクを作成
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._wait_for_tts_and_transfer(call_id))
            except RuntimeError:
                # イベントループが実行されていない場合は、_transfer_task_queueに追加
                # process_queued_transfers が定期的にチェックして処理する
                self._transfer_task_queue.append(call_id)
                self.logger.info(
                    f"TRANSFER_TASK_QUEUED: call_id={call_id} queue_len={len(self._transfer_task_queue)} "
                    "(event loop not running, will be processed by process_queued_transfers)"
                )

    async def _wait_for_tts_completion_and_update_time(self, call_id: str, tts_audio_length: int) -> None:
        """
        TTS送信完了を待って、_last_tts_end_timeを更新する
        
        :param call_id: 通話ID
        :param tts_audio_length: TTS音声データの長さ（バイト）
        """
        # TTS送信完了を待つ（is_speaking_tts が False になるまで）
        start_time = time.time()
        while self.running and self.is_speaking_tts:
            if time.time() - start_time > 30.0:  # 最大30秒待つ
                break
            await asyncio.sleep(0.1)
        
        # 追加の待機: キューが完全に空になるまで待つ
        queue_wait_start = time.time()
        while self.running and len(self.tts_queue) > 0:
            if time.time() - queue_wait_start > 2.0:  # 最大2秒待つ
                break
            await asyncio.sleep(0.05)
        
        # TTS送信完了時刻を記録（time.monotonic()で統一）
        now = time.monotonic()
        self._last_tts_end_time[call_id] = now
        self.logger.debug(
            f"[NO_INPUT] TTS completion recorded: call_id={call_id} time={now:.2f}"
        )

    async def _wait_for_tts_and_transfer(self, call_id: str, timeout: float = 10.0) -> None:
        """
        TTS送信完了を待ってから転送処理を開始する
        
        :param call_id: 通話ID
        :param timeout: タイムアウト時間（秒）
        """
        self.logger.info(f"WAIT_FOR_TTS_START: call_id={call_id} timeout={timeout}s")
        start_time = time.time()
        
        # TTS送信完了を待つ（is_speaking_tts が False になるまで）
        while self.running and self.is_speaking_tts:
            if time.time() - start_time > timeout:
                self.logger.warning(
                    f"WAIT_FOR_TTS_TIMEOUT: call_id={call_id} timeout={timeout}s. "
                    "Proceeding with transfer anyway."
                )
                break
            await asyncio.sleep(0.1)  # 100ms間隔でチェック
        
        # 追加の待機: キューが完全に空になるまで待つ（念のため）
        queue_wait_start = time.time()
        while self.running and len(self.tts_queue) > 0:
            if time.time() - queue_wait_start > 2.0:  # 最大2秒待つ
                self.logger.warning(
                    f"WAIT_FOR_TTS_QUEUE_TIMEOUT: call_id={call_id} queue not empty. "
                    "Proceeding with transfer anyway."
                )
                break
            await asyncio.sleep(0.05)  # 50ms間隔でチェック
        
        elapsed = time.time() - start_time
        self.logger.info(
            f"WAIT_FOR_TTS_COMPLETE: call_id={call_id} elapsed={elapsed:.2f}s "
            f"is_speaking_tts={self.is_speaking_tts} queue_len={len(self.tts_queue)}"
        )
        
        # 転送処理を開始
        if self._pending_transfer_call_id == call_id:
            self._pending_transfer_call_id = None
            self.logger.info(f"TRANSFER_AFTER_TTS: call_id={call_id} starting transfer")
            self._handle_transfer(call_id)
        else:
            self.logger.warning(
                f"TRANSFER_AFTER_TTS_SKIP: call_id={call_id} "
                f"pending_transfer_call_id={self._pending_transfer_call_id} (mismatch)"
            )

    async def _tts_sender_loop(self):
        self.logger.debug("TTS Sender loop started.")
        consecutive_skips = 0
        while self.running:
            if self.tts_queue and self.rtp_peer and self.rtp_transport:
                try:
                    payload = self.tts_queue.popleft()
                    packet = self.rtp_builder.build_packet(payload)
                    self.rtp_transport.sendto(packet, self.rtp_peer)
                    consecutive_skips = 0  # リセット
                except Exception as e:
                    self.logger.error(f"TTS sender failed: {e}", exc_info=True)
            else:
                # 音声送信できない or 待機中
                if self.tts_queue:
                    # rtp_peer が None の場合は、RTPパケットが来るまで待機（キューは保持）
                    if self.rtp_peer is None:
                        consecutive_skips += 1
                        if consecutive_skips == 1 or consecutive_skips % 300 == 0:  # 最初と300回ごとにログ（スパム防止）
                            self.logger.warning(
                                f"TTS_SENDER_BLOCKED: queue_len={len(self.tts_queue)} "
                                f"rtp_peer=None (waiting for RTP connection) "
                                f"rtp_transport={self.rtp_transport is not None} "
                                f"consecutive_skips={consecutive_skips}"
                            )
                    else:
                        # rtp_peer は設定されているが、rtp_transport が None の場合
                        consecutive_skips += 1
                        if consecutive_skips == 1 or consecutive_skips % 300 == 0:
                            self.logger.warning(
                                f"TTS_SENDER_BLOCKED: queue_len={len(self.tts_queue)} "
                                f"rtp_peer={self.rtp_peer} "
                                f"rtp_transport=None "
                                f"consecutive_skips={consecutive_skips}"
                            )
                if not self.tts_queue:
                    self.is_speaking_tts = False
                    consecutive_skips = 0
                    # 初回シーケンス再生が完了したらフラグをリセット
                    if self.initial_sequence_playing:
                        # スレッドスイッチを確保してからフラグを変更（非同期ループの確実な実行のため）
                        await asyncio.sleep(0.01)
                        self.initial_sequence_playing = False
                        self.logger.debug("[INITIAL_SEQUENCE] OFF: initial_sequence_playing=False (ASR will be enabled)")
            
            await asyncio.sleep(0.02)  # CPU負荷を軽減（送信間隔を20ms空ける）

    async def _streaming_poll_loop(self):
        """ストリーミングモード: 定期的にASR結果をポーリングし、確定した発話を処理する。"""
        self.logger.debug("STREAMING_LOOP: started")
        poll_count = 0
        while self.running:
            try:
                # call_idがNoneでも一時的なIDで処理（WebSocket initが来る前でも動作するように）
                effective_call_id = self._get_effective_call_id()
                result = self.ai_core.check_for_transcript(effective_call_id)
                poll_count += 1
                if result is not None:
                    self.logger.debug(f"STREAMING_LOOP: polled call_id={effective_call_id} result=FOUND (poll_count={poll_count})")
                    text, audio_duration, inference_time, end_to_text_delay = result
                    await self._process_streaming_transcript(
                        text, audio_duration, inference_time, end_to_text_delay
                    )
                # ポーリングの詳細ログはDEBUG（スパム防止）
            except Exception as e:
                self.logger.error(f"Streaming poll error: {e}", exc_info=True)
            await asyncio.sleep(0.1)  # 100ms間隔でポーリング

    async def _ws_client_loop(self):
        while self.running:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    self.websocket = websocket
                    self.logger.info("WebSocket connected (Control Plane)")
                    async for message in websocket:
                        if isinstance(message, str):
                            try:
                                data = json.loads(message)
                                msg_type = data.get("type")
                                
                                # ▼▼▼ クライアント初期化ロジック ▼▼▼
                                if msg_type == "init":
                                    try:
                                        req_client_id = data.get("client_id")
                                        req_call_id = data.get("call_id")
                                        req_caller_number = data.get("caller_number")  # caller_numberを取得
                                        self.logger.debug(f"[Init] Request for client_id: {req_client_id}")

                                        # プロファイル読み込み
                                        self.client_profile = load_client_profile(req_client_id)

                                        # メモリ展開
                                        if self.call_id and (
                                            self.client_id != req_client_id
                                            or (req_call_id and self.call_id != req_call_id)
                                        ):
                                            self._complete_console_call()
                                        self._reset_call_state()
                                        self.client_id = req_client_id
                                        self.config = self.client_profile["config"]
                                        self.rules = self.client_profile["rules"]
                                        
                                        # caller_numberをAICoreに設定
                                        if req_caller_number:
                                            self.ai_core.caller_number = req_caller_number
                                            self.logger.debug(f"[Init] Set caller_number: {req_caller_number}")
                                        else:
                                            # caller_numberが送られてこない場合はNone（後で"-"として記録される）
                                            self.ai_core.caller_number = None
                                            self.logger.debug("[Init] caller_number not provided in init message")
                                        
                                        self._ensure_console_session(call_id_override=req_call_id)
                                        self._queue_initial_audio_sequence(self.client_id)

                                        self.logger.debug(f"[Init] Loaded: {self.config.get('client_name')}")
                                    except Exception as e:
                                        self.logger.debug(f"[Init Error] {e}")
                                    continue
                                if msg_type == "call_end":
                                    try:
                                        req_call_id = data.get("call_id")
                                        if req_call_id and self.call_id == req_call_id:
                                            self._stop_recording()
                                            self._complete_console_call()
                                    except Exception as e:
                                        self.logger.error("call_end handling failed: %s", e)
                                    continue
                                # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

                            except json.JSONDecodeError:
                                pass
            except Exception:
                await asyncio.sleep(self.reconnect_delay)
            finally:
                self.websocket = None

    def _free_port(self, port: int):
        """安全にポートを解放する（自分自身は殺さない）"""
        try:
            # まずポートが使用中かチェック
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                s.close()
                self.logger.debug(f"[BOOT] Port {port} is available")
                return  # ポートが空いているので何もしない
        except OSError as e:
            if e.errno == 98:  # Address already in use
                self.logger.warning(f"[BOOT] Port {port} is in use, attempting to free it...")
                try:
                    # fuserでポートを使用しているプロセスのPIDを取得
                    res = subprocess.run(
                        ["fuser", f"{port}/tcp"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if not res.stdout.strip():
                        self.logger.debug(f"[BOOT] Port {port} appears to be free now")
                        return
                    
                    # PIDを抽出（fuserの出力例: "9001/tcp: 12345 67890"）
                    pids = []
                    for part in res.stdout.strip().split():
                        # "9001/tcp:" や "12345" のような形式からPIDを抽出
                        if part.replace(":", "").replace("/", "").isdigit():
                            pid_str = part.replace(":", "").replace("/", "")
                            if pid_str.isdigit():
                                pids.append(int(pid_str))
                        elif part.isdigit():
                            pids.append(int(part))
                    
                    # 自分自身のPIDを取得
                    current_pid = os.getpid()
                    
                    # 自分自身を除外
                    target_pids = [pid for pid in pids if pid != current_pid]
                    
                    if not target_pids:
                        self.logger.info(f"[BOOT] Port {port} in use by current process only (PID {current_pid}) — skipping kill")
                        return
                    
                    # 自分以外のプロセスのみKILL
                    pid_strs = [str(pid) for pid in target_pids]
                    subprocess.run(
                        ["kill", "-9"] + pid_strs,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False
                    )
                    self.logger.info(f"[BOOT] Port {port} freed by killing PIDs: {', '.join(pid_strs)}")
                    
                    # 少し待機してから再確認
                    import time
                    time.sleep(0.5)
                except Exception as free_error:
                    self.logger.warning(f"[BOOT] Port free check failed: {free_error}")
            else:
                self.logger.warning(f"[BOOT] Error checking port {port}: {e}")

    async def _ws_server_loop(self):
        """WebSocketサーバーとしてAsterisk側からの接続を受け付ける"""
        ws_server_port = 9001
        ws_server_host = "0.0.0.0"
        
        # WebSocket起動前にポートを確認・解放
        self.logger.debug(f"[BOOT] Checking WebSocket port {ws_server_port} availability")
        self._free_port(ws_server_port)
        
        async def handle_asterisk_connection(websocket):
            """Asterisk側からのWebSocket接続を処理"""
            self.logger.info(f"[WS Server] New connection from {websocket.remote_address}")
            try:
                async for message in websocket:
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")
                            
                            if msg_type == "init":
                                self.logger.info(f"[WS Server] INIT from Asterisk: {data}")
                                # 既存のinit処理ロジックを再利用
                                await self._handle_init_from_asterisk(data)
                            else:
                                self.logger.debug(f"[WS Server] Unknown message type: {msg_type}")
                        except json.JSONDecodeError as e:
                            self.logger.warning(f"[WS Server] Invalid JSON: {e}")
                        except Exception as e:
                            self.logger.error(f"[WS Server] Error processing message: {e}", exc_info=True)
            except websockets.exceptions.ConnectionClosed:
                self.logger.debug(f"[WS Server] Connection closed: {websocket.remote_address}")
            except Exception as e:
                self.logger.error(f"[WS Server] Connection error: {e}", exc_info=True)
        
        while self.running:
            try:
                async with websockets.serve(handle_asterisk_connection, ws_server_host, ws_server_port) as server:
                    self.logger.info(f"[WS Server] Listening on ws://{ws_server_host}:{ws_server_port}")
                    # サーバーが実際に起動したことを確認
                    if server:
                        self.logger.info(f"[WS Server] Server started successfully, waiting for connections...")
                    # サーバーを起動し続ける
                    await asyncio.Future()  # 永久に待機
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    self.logger.error(f"[WS Server] Port {ws_server_port} still in use after cleanup, retrying in 5s...")
                    await asyncio.sleep(5)
                    # 再試行前に再度ポートを解放
                    self._free_port(ws_server_port)
                    continue
                else:
                    self.logger.error(f"[WS Server] Failed to start: {e}", exc_info=True)
                    await asyncio.sleep(5)  # エラー時は5秒待って再試行
            except Exception as e:
                self.logger.error(f"[WS Server] Failed to start: {e}", exc_info=True)
                await asyncio.sleep(5)  # エラー時は5秒待って再試行

    async def _handle_init_from_asterisk(self, data: dict):
        """Asterisk側からのinitメッセージを処理（既存ロジックを再利用）"""
        req_client_id = data.get("client_id", "000")
        req_call_id = data.get("call_id")
        req_caller_number = data.get("caller_number")
        
        # caller_numberをログで確認（最初に記録）
        self.logger.info(f"[Init from Asterisk] caller_number received: {req_caller_number}")
        
        self.logger.debug(f"[Init from Asterisk] client_id={req_client_id}, call_id={req_call_id}, caller_number={req_caller_number}")

        # プロファイル読み込み（失敗時はデフォルト設定を使用）
        try:
            self.client_profile = load_client_profile(req_client_id)
        except FileNotFoundError as e:
            self.logger.warning(f"[Init from Asterisk] Config file not found for {req_client_id}, using default: {e}")
            # デフォルト設定を使用
            self.client_profile = {
                "client_id": req_client_id,
                "base_dir": f"/opt/libertycall/clients/{req_client_id}",
                "log_dir": f"/opt/libertycall/logs/calls/{req_client_id}",
                "config": {
                    "client_name": "Default",
                    "save_calls": True,
                },
                "rules": {}
            }
        except Exception as e:
            self.logger.error(f"[Init from Asterisk] Failed to load client profile: {e}", exc_info=True)
            # エラー時もデフォルト設定を使用して処理を続行
            self.client_profile = {
                "client_id": req_client_id,
                "base_dir": f"/opt/libertycall/clients/{req_client_id}",
                "log_dir": f"/opt/libertycall/logs/calls/{req_client_id}",
                "config": {
                    "client_name": "Default",
                    "save_calls": True,
                },
                "rules": {}
            }

        # メモリ展開
        try:
            if self.call_id and (
                self.client_id != req_client_id
                or (req_call_id and self.call_id != req_call_id)
            ):
                self._complete_console_call()
            self._reset_call_state()
            self.client_id = req_client_id
            self.config = self.client_profile["config"]
            self.rules = self.client_profile["rules"]
            
            # caller_numberをAICoreに設定（config読み込み失敗時も必ず実行）
            # "-" や空文字列の場合は None に変換
            if req_caller_number and req_caller_number.strip() and req_caller_number not in ("-", ""):
                self.ai_core.caller_number = req_caller_number.strip()
                self.logger.info(f"[Init from Asterisk] Set caller_number: {req_caller_number.strip()}")
            else:
                self.ai_core.caller_number = None
                self.logger.warning(f"[Init from Asterisk] caller_number not provided or invalid (received: {req_caller_number})")
            
            # caller_numberをログで確認（DB保存前）
            caller_number_for_db = getattr(self.ai_core, "caller_number", None)
            self.logger.info(f"[Init from Asterisk] caller_number for DB: {caller_number_for_db}")
            
            # DB保存処理（config読み込み失敗時も必ず実行）
            self._ensure_console_session(call_id_override=req_call_id)
            
            # caller_numberがDBに保存されたことをログで確認
            if caller_number_for_db:
                self.logger.info(f"[Init from Asterisk] caller_number saved to DB: {caller_number_for_db}")
            
            # 管理画面用に通話情報を明示的にログ出力（call_id / caller_number / timestamp）
            try:
                now_ts = datetime.now().isoformat()
                self.logger.info(
                    f"[CallInfo] call_id={self.call_id or req_call_id} caller={caller_number_for_db} timestamp={now_ts} status=in_progress"
                )
            except Exception as e:
                self.logger.warning(f"[CallInfo] failed to log call info for UI: {e}")
            
            self._queue_initial_audio_sequence(self.client_id)

            self.logger.debug(f"[Init from Asterisk] Loaded: {self.config.get('client_name', 'Default')}")
            
            # 【デバッグ】無音タイマー設定をログ出力
            self.logger.info(
                f"[DEBUG_INIT] No-input timer settings: NO_INPUT_TIMEOUT={self.NO_INPUT_TIMEOUT}s, "
                f"MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s, NO_INPUT_STREAK_LIMIT={self.NO_INPUT_STREAK_LIMIT}"
            )
            
            # 通話開始時点では無音検知タイマーを起動しない
            # （初期アナウンス再生完了後に起動する）
            # effective_call_id = self.call_id or req_call_id
            # if effective_call_id:
            #     self.logger.debug(f"[DEBUG_INIT] Starting no_input_timer at call start for call_id={effective_call_id}")
            #     self._start_no_input_timer(effective_call_id)
        except Exception as e:
            self.logger.error(f"[Init from Asterisk] Error during initialization: {e}", exc_info=True)
            # エラーが発生してもcaller_numberの設定とDB保存だけは試みる
            if req_caller_number and req_caller_number.strip() and req_caller_number not in ("-", ""):
                self.ai_core.caller_number = req_caller_number.strip()
                self.logger.info(f"[Init from Asterisk] Set caller_number (fallback): {req_caller_number.strip()}")
                # 最小限のDB保存処理を試みる
                try:
                    self._ensure_console_session(call_id_override=req_call_id)
                    self.logger.info(f"[Init from Asterisk] caller_number saved to DB (fallback): {req_caller_number.strip()}")
                except Exception as db_error:
                    self.logger.error(f"[Init from Asterisk] Failed to save caller_number to DB: {db_error}", exc_info=True)

    def _is_silent_ulaw(self, data: bytes, threshold: float = 0.005) -> bool:
        """
        μ-lawデータをPCMに変換してエネルギー判定を行い、無音かどうかを判定
        
        :param data: μ-lawエンコードされた音声データ
        :param threshold: RMS閾値（デフォルト: 0.005）
        :return: 無音の場合True、有音の場合False
        """
        try:
            import numpy as np
            # μ-law → PCM16変換
            pcm = np.frombuffer(audioop.ulaw2lin(data, 2), dtype=np.int16)
            # RMS計算（正規化: -32768～32767 → -1.0～1.0）
            rms = np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2))
            return rms < threshold
        except Exception as e:
            # エラー時は有音と判定（安全側に倒す）
            self.logger.debug(f"[RTP_SILENT] Error in _is_silent_ulaw: {e}")
            return False

    async def handle_rtp_packet(self, data: bytes, addr: Tuple[str, int]):
        # RTPパケット受信ログ（必ず出力）
        self.logger.debug(f"[RTP_RECV] packet received from {addr}, len={len(data)}")
        try:
            # RTPパケット受信カウンターを初期化（存在しない場合）
            if not hasattr(self, "_rtp_recv_count"):
                self._rtp_recv_count = 0
            self._rtp_recv_count += 1
            
            # RTPピアの設定・変更をログに記録
            last_peer_state = self.rtp_peer  # RTP確立前の状態を記録
            if self.rtp_peer is None:
                self.logger.warning(f"[RTP_INIT] First RTP packet from {addr}, setting as peer")
                self.rtp_peer = addr
                # RTP確立時に古すぎるTTSを安全に間引く
                if len(self.tts_queue) > 30:
                    drop = len(self.tts_queue) - 30
                    for _ in range(drop):
                        self.tts_queue.popleft()
                    self.logger.warning(f"[TTS_QUEUE_TRIM] dropped {drop} old items after RTP established (queue_len was {len(self.tts_queue) + drop})")
                self.logger.info(f"[TTS_SENDER] RTP peer established: {self.rtp_peer}, queue_len={len(self.tts_queue)}")
            elif addr != self.rtp_peer:
                self.logger.warning(f"[RTP_SWITCH] RTP source changed from {self.rtp_peer} to {addr}")
                self.rtp_peer = addr
            elif self._rtp_recv_count % 100 == 0:
                self.logger.debug(f"[RTP_RECV] received {self._rtp_recv_count} packets from {addr}")
        except Exception as e:
            self.logger.error(f"[RTP_RECV_ERROR] {e}", exc_info=True)
        
        self.logger.debug(
            "HANDLE_RTP_ENTRY: len=%d addr=%s call_completed=%s call_id=%s",
            len(data),
            addr,
            getattr(self, 'call_completed', False),
            getattr(self, 'call_id', None),
        )
        now = time.time()
        if self.rtp_peer is None:
            self.rtp_peer = addr
            self.logger.debug(f"RTP peer detected: {addr}")
        elif addr != self.rtp_peer:
            idle = now - self.last_rtp_packet_time if self.last_rtp_packet_time else None
            if idle is None or idle >= self.RTP_PEER_IDLE_TIMEOUT:
                self.logger.info(
                    "RTP peer changed from %s to %s (idle=%.2fs) -> resetting call state",
                    self.rtp_peer,
                    addr,
                    idle if idle is not None else -1.0,
                )
                if self.call_id:
                    self._complete_console_call()
                # ★ 常に完全なリセットを実行
                self._reset_call_state()
                self.rtp_peer = addr
                self.logger.debug(f"RTP peer re-bound: {addr}")
            else:
                self.logger.debug(
                    "Ignoring unexpected RTP packet from %s (active peer=%s idle=%.2fs)",
                    addr,
                    self.rtp_peer,
                    idle,
                )
                return
        
        self.last_rtp_packet_time = now

        if len(data) <= 12:
            return
        
        # RTPペイロードを抽出（μ-law）
        pcm_data = data[12:]
        
        # 最初のRTP到着時に初期音声を強制再生
        effective_call_id = self._get_effective_call_id(addr)
        if not effective_call_id:
            self.logger.warning(f"[RTP_WARN] Unknown RTP source {addr}, skipping frame")
            return  # TEMP_CALLを使わずスキップ
        
        # ログ出力（RTP受信時のcall_id確認用）
        self.logger.debug(f"[HANDLE_RTP_ENTRY] len={len(data)} addr={addr} call_id={effective_call_id}")
        
        if effective_call_id and effective_call_id not in self._initial_tts_sent:
            self._initial_tts_sent.add(effective_call_id)
            self.logger.debug(f"[INIT_TTS_FORCE] First RTP detected -> Playing initial TTS for call_id={effective_call_id}")
            asyncio.create_task(self._play_tts(effective_call_id, "リバティーコールです。"))
        
        # 無音判定（RTPペイロードのエネルギー判定）
        if effective_call_id:
            current_time = time.monotonic()
            threshold = 0.005
            
            # RMS値を計算（有音・無音判定用）
            try:
                import numpy as np
                # μ-law → PCM16変換
                pcm = np.frombuffer(audioop.ulaw2lin(pcm_data, 2), dtype=np.int16)
                # RMS計算（正規化: -32768～32767 → -1.0～1.0）
                rms = np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2))
                is_voice = rms >= threshold
            except Exception as e:
                # エラー時は有音と判定（安全側に倒す）
                self.logger.debug(f"[RTP_SILENT] Error in RMS calculation: {e}")
                rms = threshold
                is_voice = True
            
            if is_voice:
                # 有音検出時のみ _last_voice_time を更新
                self._last_voice_time[effective_call_id] = current_time
                # 有音を検出したら無音記録をリセット
                if effective_call_id in self._last_silence_time:
                    del self._last_silence_time[effective_call_id]
                    self.logger.debug(f"[RTP_VOICE] Voice detected (RMS={rms:.4f}) for call_id={effective_call_id}, resetting silence time")
                # 有音フレーム検出時は無音カウンターをリセット
                if hasattr(self, "_silent_frame_count"):
                    self._silent_frame_count = 0
            else:
                # 無音時は _last_voice_time を更新しない（ただし初回のみ初期化）
                # 初回の無音だけ記録（連続無音なら上書きしない）
                if effective_call_id not in self._last_silence_time:
                    self._last_silence_time[effective_call_id] = current_time
                    self.logger.debug(f"[RTP_SILENT] First silent frame detected (RMS={rms:.4f}) for call_id={effective_call_id} at {current_time:.1f}")
                # RTPストリームが届いたという事実を記録（_last_voice_time が存在しない場合のみ初期化）
                if effective_call_id not in self._last_voice_time:
                    self._last_voice_time[effective_call_id] = current_time
                    self.logger.debug(f"[RTP_INIT] Initialized _last_voice_time for silent stream call_id={effective_call_id}")
                # デバッグログは頻度を下げる（100フレームに1回）
                if not hasattr(self, "_silent_frame_count"):
                    self._silent_frame_count = 0
                self._silent_frame_count += 1
                if self._silent_frame_count % 100 == 0:
                    self.logger.debug(f"[RTP_SILENT] Detected silent frame (RMS < {threshold}) count={self._silent_frame_count}")
        
        # call_idが未設定の場合は、最初のRTPパケット受信時に設定
        if not self.call_id:
            self._ensure_console_session()
        
        # 最初のRTPパケット受信時に _active_calls に登録（確実なタイミング）
        # effective_call_id は上記の無音判定ブロックで取得済み
        if effective_call_id and effective_call_id not in self._active_calls:
            self._active_calls.add(effective_call_id)
            self.logger.debug(f"[RTP_ACTIVE] Registered call_id={effective_call_id} to _active_calls")
            # アドレスとcall_idのマッピングを保存
            if addr:
                self._call_addr_map[addr] = effective_call_id
                self.logger.debug(f"[RTP_ADDR_MAP] Mapped {addr} -> {effective_call_id}")
            
        # RTPパケット受信ログ（Google使用時は毎回INFO、それ以外は50パケットに1回）
        self.rtp_packet_count += 1
        asr_provider = getattr(self.ai_core, 'asr_provider', 'google')
        is_google_streaming = (asr_provider == "google" and self.streaming_enabled)
        
        # 最初の RTP パケット受信時に初回シーケンスを enqueue
        # client_id が設定されていない場合は default_client_id を使用
        if not self.initial_sequence_played and self.rtp_packet_count == 1:
            effective_client_id = self.client_id or self.default_client_id
            if effective_client_id:
                self._queue_initial_audio_sequence(effective_client_id)
            else:
                self.logger.warning("No client_id available for initial sequence, skipping")
            
            # 録音開始（最初の RTP パケット受信時）
            if self.recording_enabled and self.recording_file is None:
                self._start_recording()

        if is_google_streaming:
            # Google使用時は毎回INFOレベルで出力（idx付き）
            self.logger.info(
                "RTP_RECV: n=%d time=%.3f from=%s size=%d",
                self.rtp_packet_count, time.time(), addr, len(data)
            )
        elif self.rtp_packet_count == 1:
            self.logger.info(f">> RTP packet received from {addr}, size={len(data)}")
        elif self.rtp_packet_count % 50 == 0:
            self.logger.info(f">> RTP packet received (count={self.rtp_packet_count}) from {addr}, size={len(data)}")
        else:
            self.logger.debug(f">> RTP packet received from {addr}, size={len(data)}")
            
        # pcm_data は既に上で抽出済み（無音判定で使用）
        
        try:
            # μ-law → PCM16 (8kHz) に変換
            pcm16_8k = audioop.ulaw2lin(pcm_data, 2)
            rms = audioop.rms(pcm16_8k, 2)
            
            # --- 音量レベル送信（管理画面用） ---
            self._maybe_send_audio_level(rms)

            # --- バージイン判定（TTS停止のため常に有効） ---
            # 初回シーケンス再生中はバージインを無効化（000→001→002 が必ず流れるように）
            # Googleストリーミング使用時でも、TTS停止のためのBarge-in判定は有効化
            if not self.initial_sequence_playing:
                if rms > self.BARGE_IN_THRESHOLD:
                    self.is_user_speaking = True
                    self.last_voice_time = time.time()
                    
                    # 音声が受信された際に無音検知タイマーをリセット
                    effective_call_id = self._get_effective_call_id()
                    if effective_call_id:
                        self.logger.debug(f"[on_audio_activity] Resetting no_input_timer for call_id={effective_call_id} (barge-in detected)")
                        try:
                            # 直接 create_task を使用（async def 内なので）
                            task = asyncio.create_task(self._start_no_input_timer(effective_call_id))
                            self.logger.debug(
                                f"[DEBUG_INIT] Scheduled no_input_timer task on barge-in for call_id={effective_call_id}, task={task}"
                            )
                        except Exception as e:
                            self.logger.exception(
                                f"[NO_INPUT] Failed to schedule no_input_timer on barge-in for call_id={effective_call_id}: {e}"
                            )
                    
                    if self.is_speaking_tts:
                        self.logger.info(">> Barge-in: TTS Stopped (RMS=%d, threshold=%d).", rms, self.BARGE_IN_THRESHOLD)
                        self.tts_queue.clear()
                        self.is_speaking_tts = False
                        # バージイン時もバッファとタイマーをクリア
                        self.audio_buffer = bytearray()
                        self.current_segment_start = None

            # WebRTC Noise Suppressor適用（8kHz PCM16 → NS → 8kHz PCM16）
            if self.ns is not None:
                pcm16_8k_ns = self.ns.process_stream(pcm16_8k)
            else:
                pcm16_8k_ns = pcm16_8k  # NSが利用できない場合はそのまま使用
            
            # 録音（8kHz PCM16 をそのまま記録）
            if self.recording_enabled and self.recording_file is not None:
                try:
                    self.recording_file.writeframes(pcm16_8k_ns)
                except Exception as e:
                    self.logger.error(f"録音エラー: {e}", exc_info=True)
            
            # 8kHz → 16kHz リサンプリング（resample_poly使用）
            import numpy as np
            from scipy.signal import resample_poly
            pcm16_array = np.frombuffer(pcm16_8k_ns, dtype=np.int16)
            pcm16k_array = resample_poly(pcm16_array, 2, 1)  # 8kHz → 16kHz
            pcm16k_chunk = pcm16k_array.astype(np.int16).tobytes()
            
            # --- 初回シーケンス再生中は ASR には送らない（録音とRMSだけ） ---
            if self.initial_sequence_playing:
                # 録音は続けるが、ASRには一切送らない
                # ログは最初の1回だけ出力（スパム防止）
                if not hasattr(self, '_asr_skip_logged'):
                    self.logger.info(
                        "[INITIAL_SEQUENCE] ASR_SKIP: initial_sequence_playing=True, skipping ASR feed (recording continues)"
                    )
                    self._asr_skip_logged = True
                return
            # 初回シーケンス終了後はログフラグをリセット
            if hasattr(self, '_asr_skip_logged'):
                delattr(self, '_asr_skip_logged')
            
            # --- ストリーミングモード: チャンクごとにfeed ---
            # Google使用時は全チャンクを無条件で送信（VAD/バッファリングなし）
            if self.streaming_enabled:
                # call_idがNoneでも一時的なIDで処理（WebSocket initが来る前でも動作するように）
                effective_call_id = self._get_effective_call_id()
                
                # 通常のストリーミング処理
                self._stream_chunk_counter += 1
                
                # 前回からの経過時間を計算
                current_time = time.time()
                dt_ms = (current_time - self._last_feed_time) * 1000
                self._last_feed_time = current_time
                
                # RMS記録（統計用）
                if self.is_user_speaking:
                    self.turn_rms_values.append(rms)
                
                # ログ出力（頻度を下げる：10チャンクに1回、最初のチャンク、またはRMS閾値超過時）
                should_log_info = (
                    self._stream_chunk_counter % 10 == 0 or
                    self._stream_chunk_counter == 1 or
                    rms > self.BARGE_IN_THRESHOLD
                )
                if should_log_info:
                    self.logger.info(
                        f"STREAMING_FEED: idx={self._stream_chunk_counter} dt={dt_ms:.1f}ms "
                        f"call_id={effective_call_id} len={len(pcm16k_chunk)} rms={rms}"
                    )
                else:
                    self.logger.debug(
                        f"STREAMING_FEED: idx={self._stream_chunk_counter} dt={dt_ms:.1f}ms"
                    )
                
                # ASRへ送信（エラーハンドリング付き）
                try:
                    self.ai_core.on_new_audio(effective_call_id, pcm16k_chunk)
                except Exception as e:
                    self.logger.error(f"ASR feed error: {e}", exc_info=True)
                
                # ストリーミングモードではここで処理終了
                # （従来のバッファリングロジックはスキップ）
                return
            
            # --- バッファリング（非ストリーミングモード） ---
            # 初回シーケンス再生中は ASR をブロック（000→001→002 が必ず流れるように）
            if self.initial_sequence_playing:
                return
            
            self.audio_buffer.extend(pcm16k_chunk)
            
            # ★ 最初の音声パケット到達時刻を記録
            if self.current_segment_start is None:
                self.current_segment_start = time.time()

            if self.is_user_speaking:
                self.turn_rms_values.append(rms)

            # --- ストリーミングモードでは従来のバッファリング処理をスキップ ---
            if self.streaming_enabled:
                return
            
            # --- ターミネート(区切り)判定（非ストリーミングモード） ---
            now = time.time()
            time_since_voice = now - self.last_voice_time
            
            # セグメント経過時間を計算 (未開始なら0)
            segment_elapsed = 0.0
            if self.current_segment_start is not None:
                segment_elapsed = now - self.current_segment_start

            # ★ ハイブリッド条件
            # 1. 無音が SILENCE_DURATION 続いた
            # 2. または、話し始めてから MAX_SEGMENT_SEC 経過した
            should_cut = False
            
            # A. 無音タイムアウト
            if self.is_user_speaking and (time_since_voice > self.SILENCE_DURATION):
                should_cut = True
            
            # B. 最大時間タイムアウト (音声がある場合のみ)
            elif len(self.audio_buffer) > 0 and (segment_elapsed > self.MAX_SEGMENT_SEC):
                should_cut = True
                self.logger.debug(f">> MAX SEGMENT REACHED ({segment_elapsed:.2f}s). Forcing cut.")

            if should_cut:
                # ノイズ除去: バッファが短すぎる場合は破棄
                if len(self.audio_buffer) < self.MIN_AUDIO_LEN:
                     self.audio_buffer = bytearray()
                     self.turn_rms_values = []
                     self.current_segment_start = None # リセット
                     return 

                self.logger.debug(">> Processing segment...")
                self.is_user_speaking = False
                
                user_audio = bytes(self.audio_buffer)
                
                # RMSベースのノイズゲート: 低RMSのセグメントはASRに送らない
                if self.turn_rms_values:
                    rms_avg = sum(self.turn_rms_values) / len(self.turn_rms_values)
                else:
                    rms_avg = 0
                
                if rms_avg < self.MIN_RMS_FOR_ASR:
                    self.logger.debug(
                        f">> Segment skipped due to low RMS (rms_avg={rms_avg:.1f})"
                    )
                    # セグメントを破棄してリセット
                    self.audio_buffer.clear()
                    self.turn_rms_values = []
                    self.current_segment_start = None
                    self.is_user_speaking = False
                    return
                
                # 処理開始前にバッファとタイマーをリセット
                self.audio_buffer = bytearray()
                self.current_segment_start = None 
                
                # AI処理実行
                self._ensure_console_session()
                tts_audio_24k, should_transfer, text_raw, intent, reply_text = self.ai_core.process_dialogue(user_audio)
                
                # 音声が検出された際に無音検知タイマーをリセット
                if text_raw and intent != "IGNORE":
                    effective_call_id = self._get_effective_call_id()
                    if effective_call_id:
                        self.logger.debug(f"[on_audio_activity] Resetting no_input_timer for call_id={effective_call_id} (segment processed)")
                        try:
                            # 直接 create_task を使用（async def 内なので）
                            task = asyncio.create_task(self._start_no_input_timer(effective_call_id))
                            self.logger.debug(
                                f"[DEBUG_INIT] Scheduled no_input_timer task on segment processed for call_id={effective_call_id}, task={task}"
                            )
                        except Exception as e:
                            self.logger.exception(
                                f"[NO_INPUT] Failed to schedule no_input_timer on segment processed for call_id={effective_call_id}: {e}"
                            )
                
                if text_raw and intent != "IGNORE":
                    # ★ user_turn_index のインクリメントを非ストリーミングモードと統一
                    self.user_turn_index += 1
                    state_label = (intent or self.current_state).lower()
                    self.current_state = state_label
                    self._record_dialogue("ユーザー", text_raw)
                    self._append_console_log("user", text_raw, state_label)
                else:
                    state_label = self.current_state

                if reply_text:
                    self._record_dialogue("AI", reply_text)
                    self._append_console_log("ai", reply_text, self.current_state)
                
                if tts_audio_24k:
                    ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
                    chunk_size = 160
                    for i in range(0, len(ulaw_response), chunk_size):
                        self.tts_queue.append(ulaw_response[i:i+chunk_size])
                    self.logger.debug(f">> TTS Queued")
                    self.is_speaking_tts = True

                if should_transfer:
                    self.logger.info(f">> TRANSFER REQUESTED to {OPERATOR_NUMBER}")
                    # 転送処理を実行
                    effective_call_id = self._get_effective_call_id()
                    self._handle_transfer(effective_call_id)

                # ログ出力
                if self.turn_rms_values:
                    rms_avg = sum(self.turn_rms_values) / len(self.turn_rms_values)
                else:
                    rms_avg = 0
                self.turn_rms_values = []

                # 実際の音声データ長から正確な秒数を算出
                duration = len(user_audio) / 2 / 16000.0
                text_norm = normalize_text(text_raw) if text_raw else ""
                
                # ★ turn_id管理: 非ストリーミングモードでのユーザー発話カウンター
                self.logger.debug(f"TURN {self.turn_id}: RMS_AVG={rms_avg:.1f}, DURATION={duration:.2f}s, TEXT_RAW={text_raw}, TEXT_NORM={text_norm}, INTENT={intent}")
                self.turn_id += 1

        except Exception as e:
            self.logger.error(f"AI Error: {e}")

    async def shutdown(self):
        """Graceful shutdown for RTP transport and all resources"""
        self.logger.info("[SHUTDOWN] Starting graceful shutdown...")
        self.running = False
        self._complete_console_call()
        
        # WebSocket接続を閉じる
        if self.websocket:
            try:
                await self.websocket.close()
                self.logger.debug("[SHUTDOWN] WebSocket closed")
            except Exception as e:
                self.logger.warning(f"[SHUTDOWN] Error while closing WebSocket: {e}")
        
        # RTP transport を優雅に閉じる
        if self.rtp_transport:
            try:
                self.logger.info("[SHUTDOWN] Closing RTP transport...")
                self.rtp_transport.close()
                # 少し待機して確実に閉じる
                await asyncio.sleep(0.1)
                self.logger.info("[SHUTDOWN] RTP transport closed")
            except Exception as e:
                self.logger.error(f"[SHUTDOWN] Error while closing RTP transport: {e}")
        
        # 無音検知タイマーを全てキャンセル
        for call_id, timer_task in list(self._no_input_timers.items()):
            if timer_task and not timer_task.done():
                try:
                    timer_task.cancel()
                    self.logger.debug(f"[SHUTDOWN] Cancelled no_input_timer for call_id={call_id}")
                except Exception as e:
                    self.logger.warning(f"[SHUTDOWN] Error cancelling timer for call_id={call_id}: {e}")
        self._no_input_timers.clear()
        
        # シャットダウンイベントを設定
        self.shutdown_event.set()
        self.logger.info("[SHUTDOWN] Graceful shutdown completed")

    # ------------------------------------------------------------------ console bridge helpers
    def _ensure_console_session(self, call_id_override: Optional[str] = None) -> None:
        """コンソールセッションを確保（call_idが未設定の場合は正式なcall_idを生成）"""
        if not self.console_bridge.enabled:
            return
        if not self.client_id:
            return
        
        # call_id_overrideが指定されている場合はそれを使用
        if call_id_override:
            # 既存のcall_idと異なる場合は、元のcall_idを保持（ハンドオフ時の統合用）
            if self.call_id and self.call_id != call_id_override:
                self.logger.info(
                    f"Call ID override: keeping original call_id={self.call_id}, new={call_id_override}"
                )
                # 元のcall_idを保持（ハンドオフ時も同じcall_idを使用）
                # call_id_overrideは無視して、元のcall_idを継続使用
                return
            self.call_id = call_id_override
        elif not self.call_id:
            # call_idが未設定の場合は正式なcall_idを生成（TEMP_CALLは使わない）
            self.call_id = self.console_bridge.issue_call_id(self.client_id)
            self.logger.info(f"Generated new call_id: {self.call_id}")
        
        self.logger.debug("Console session started: %s", self.call_id)
        
        # AICoreにcall_idを設定（WAV保存用）
        if self.call_id:
            self.ai_core.set_call_id(self.call_id)
        if self.client_id:
            self.ai_core.client_id = self.client_id
        
        # 通話開始時刻を記録（補正用）
        if self.call_id and self.call_start_time is None:
            self.call_start_time = time.time()
            self.user_turn_index = 0  # リセット
        
        self.recent_dialogue.clear()
        self.transfer_notified = False
        self.call_completed = False
        self.current_state = "init"
        # caller_numberを取得（ai_coreから）
        caller_number = getattr(self.ai_core, "caller_number", None)
        
        # caller_numberをログで確認（DB保存前）
        self.logger.info(f"[_ensure_console_session] caller_number: {caller_number} (call_id={self.call_id})")
        
        self.console_bridge.start_call(
            self.call_id,
            self.client_id,
            state=self.current_state,
            started_at=datetime.utcnow(),
            caller_number=caller_number,
        )

    def _append_console_log(
        self,
        role: str,
        text: Optional[str],
        state: str,
        template_id: Optional[str] = None,
    ) -> None:
        if not self.console_bridge.enabled or not text:
            return
        
        # call_idが未設定の場合は正式なcall_idを生成（TEMP_CALLは使わない）
        if not self.call_id:
            if self.client_id:
                self.call_id = self.console_bridge.issue_call_id(self.client_id)
                self.logger.debug(f"Generated call_id for log: {self.call_id}")
                # AICoreにcall_idを設定
                if self.call_id:
                    self.ai_core.set_call_id(self.call_id)
            else:
                self.logger.warning("Cannot append log: call_id and client_id are not set")
                return
        
        # caller_numberを取得（ai_coreから）
        caller_number = getattr(self.ai_core, "caller_number", None)
        
        self.console_bridge.append_log(
            self.call_id,
            role=role,
            text=text,
            state=state,
            client_id=self.client_id,
            caller_number=caller_number,
            template_id=template_id,
        )

    def _record_dialogue(self, role_label: str, text: Optional[str]) -> None:
        if not text:
            return
        self.recent_dialogue.append((role_label, text.strip()))

    def _request_transfer(self, call_id: str) -> None:
        state_label = f"AI_HANDOFF:{call_id or 'UNKNOWN'}"
        self.logger.debug("RealtimeGateway: transfer callback invoked (%s)", state_label)
        self._handle_transfer(call_id)

    def _handle_transfer(self, call_id: str) -> None:
        """
        転送処理を実行
        - console_bridge に転送を記録
        - ログに転送先番号を記録（Asterisk側での確認用）
        - Asterisk に channel redirect を指示
        """
        self.logger.info(
            "TRANSFER_TO_OPERATOR_START: call_id=%s self.call_id=%s transfer_notified=%s",
            call_id,
            self.call_id,
            self.transfer_notified
        )
        
        # transfer_notified のチェックを削除
        # 理由: 同じ通話内で複数回転送を試みる場合や、転送が失敗した場合に再試行できるようにするため
        # ただし、state.transfer_executed で二重実行を防ぐ（ai_core側で制御）
        if self.transfer_notified:
            self.logger.info(
                "TRANSFER_TO_OPERATOR_RETRY: call_id=%s previous_notified=True (allowing retry)",
                call_id
            )
            # transfer_notified をリセットして再試行を許可
            self.transfer_notified = False
        
        # call_idが未設定の場合は正式なcall_idを生成（TEMP_CALLは使わない）
        if not self.call_id:
            if self.client_id:
                self.call_id = self.console_bridge.issue_call_id(self.client_id)
                self.logger.info(
                    "TRANSFER_TO_OPERATOR: generated call_id=%s (was None)",
                    self.call_id
                )
                # AICoreにcall_idを設定
                if self.call_id:
                    self.ai_core.set_call_id(self.call_id)
            else:
                self.logger.warning(
                    "TRANSFER_TO_OPERATOR_SKIP: call_id=%s reason=no_self_call_id_and_no_client_id",
                    call_id
                )
                # call_id パラメータがあれば、self.call_id に設定を試みる
                if call_id:
                    self.call_id = call_id
                    self.logger.info(
                        "TRANSFER_TO_OPERATOR: set self.call_id=%s from parameter",
                        call_id
                    )
                else:
                    return
        
        state_label = f"AI_HANDOFF:{call_id or 'UNKNOWN'}"
        
        # 転送先番号をログに記録（Asterisk側での確認用）
        self.logger.info(
            "TRANSFER_TO_OPERATOR: call_id=%s target_number=%s",
            self.call_id,
            OPERATOR_NUMBER
        )
        
        # ステップ1: 転送前に現在の会話ログを保存（call_idが既に設定されているので永続化済み）
        # 現在のcall_idで既にログが記録されているため、追加の保存処理は不要
        # ただし、caller_numberを確実に保持するために、ai_coreから取得して設定
        caller_number = getattr(self.ai_core, "caller_number", None)
        if caller_number and self.console_bridge.enabled:
            self.logger.info(
                "TRANSFER_TO_OPERATOR: preserving caller_number=%s for call_id=%s",
                caller_number,
                self.call_id
            )
        
        # console_bridge に転送を記録
        if self.console_bridge.enabled:
            summary = self._build_handover_summary(state_label)
            self.console_bridge.mark_transfer(self.call_id, summary)
            self.logger.info(
                "TRANSFER_TO_OPERATOR: console_bridge marked transfer call_id=%s",
                self.call_id
            )
        
        # Asterisk に handoff redirect を依頼（非同期で実行）
        # ステップ3: caller_numberを環境変数として渡して、handoff_redirect.pyで保持
        try:
            try:
                project_root = _PROJECT_ROOT  # 既存の定義を優先
            except NameError:
                project_root = "/opt/libertycall"
            script_path = os.path.join(project_root, "scripts", "handoff_redirect.py")
            self.logger.info(
                "TRANSFER_TO_OPERATOR: Spawning handoff_redirect script_path=%s call_id=%s caller_number=%s",
                script_path,
                self.call_id,
                caller_number or "(none)"
            )
            # ステップ3: caller_numberを環境変数として渡して、handoff_redirect.pyで保持
            env = os.environ.copy()
            if caller_number:
                env["LC_CALLER_NUMBER"] = caller_number
            env["LC_CALL_ID"] = str(self.call_id)
            env["LC_CLIENT_ID"] = str(self.client_id or "000")
            
            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            self.logger.info(
                "TRANSFER_TO_OPERATOR: handoff_redirect spawned pid=%d call_id=%s",
                proc.pid,
                self.call_id
            )
        except Exception as e:
            self.logger.exception(
                "TRANSFER_TO_OPERATOR_FAILED: Failed to spawn handoff_redirect call_id=%s error=%r",
                self.call_id,
                e
            )
        
        self.transfer_notified = True
        self.logger.info(
            "TRANSFER_TO_OPERATOR_DONE: call_id=%s transfer_notified=True",
            self.call_id
        )

    def _handle_hangup(self, call_id: str) -> None:
        """
        自動切断処理を実行
        - console_bridge に切断を記録
        - Asterisk に hangup を指示
        """
        # 発信者番号を取得（ログ出力用）
        caller_number = getattr(self.ai_core, "caller_number", None) or "未設定"
        
        self.logger.debug(f"[FORCE_HANGUP] HANGUP_REQUEST: call_id={call_id} self.call_id={self.call_id} caller={caller_number}")
        self.logger.info(
            f"[FORCE_HANGUP] HANGUP_REQUEST: call_id={call_id} self.call_id={self.call_id} caller={caller_number}"
        )
        
        # call_id が未設定の場合はパラメータから設定
        if not self.call_id and call_id:
            self.call_id = call_id
            self.logger.info(
                f"[FORCE_HANGUP] HANGUP_REQUEST: set self.call_id={call_id} from parameter caller={caller_number}"
            )
        
        if not self.call_id:
            self.logger.warning(
                f"[FORCE_HANGUP] HANGUP_REQUEST_SKIP: call_id={call_id} caller={caller_number} reason=no_self_call_id"
            )
            return
        
        # 無音経過時間をログに記録
        elapsed = self._no_input_elapsed.get(self.call_id, 0.0)
        no_input_streak = 0
        state = self.ai_core._get_session_state(self.call_id)
        if state:
            no_input_streak = state.no_input_streak
        
        self.logger.warning(
            f"[FORCE_HANGUP] Disconnecting call_id={self.call_id} caller={caller_number} "
            f"after {elapsed:.1f}s of silence (streak={no_input_streak}, MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s)"
        )
        
        # 録音を停止
        self._stop_recording()
        
        # console_bridge に切断を記録
        if self.console_bridge.enabled:
            self.console_bridge.complete_call(self.call_id, ended_at=datetime.utcnow())
            self.logger.info(
                f"[FORCE_HANGUP] console_bridge marked hangup call_id={self.call_id} caller={caller_number}"
            )
        
        # 通話終了時の状態クリーンアップ
        call_id_to_cleanup = self.call_id or call_id
        if call_id_to_cleanup:
            if hasattr(self, '_active_calls'):
                self._active_calls.discard(call_id_to_cleanup)
            self._last_voice_time.pop(call_id_to_cleanup, None)
            self._last_silence_time.pop(call_id_to_cleanup, None)
            self._last_tts_end_time.pop(call_id_to_cleanup, None)
            self._last_user_input_time.pop(call_id_to_cleanup, None)
            self._silence_warning_sent.pop(call_id_to_cleanup, None)
            if hasattr(self, '_initial_tts_sent'):
                self._initial_tts_sent.discard(call_id_to_cleanup)
            self.logger.debug(f"[CALL_CLEANUP] Cleared state for call_id={call_id_to_cleanup}")
        
        # Asterisk に hangup を依頼（非同期で実行）
        try:
            try:
                project_root = _PROJECT_ROOT  # 既存の定義を優先
            except NameError:
                project_root = "/opt/libertycall"
            script_path = os.path.join(project_root, "scripts", "hangup_call.py")
            self.logger.info(
                f"[FORCE_HANGUP] HANGUP_REQUEST: Spawning hangup_call script_path={script_path} call_id={self.call_id} caller={caller_number}"
            )
            proc = subprocess.Popen(
                [sys.executable, script_path, self.call_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.logger.info(
                f"[FORCE_HANGUP] HANGUP_REQUEST: hangup_call spawned pid={proc.pid} call_id={self.call_id} caller={caller_number}"
            )
        except Exception as e:
            self.logger.exception(
                f"[FORCE_HANGUP] HANGUP_REQUEST_FAILED: Failed to spawn hangup_call call_id={self.call_id} caller={caller_number} error={e!r}"
            )
        
        self.logger.info(
            "HANGUP_REQUEST_DONE: call_id=%s",
            self.call_id
        )

    def _build_handover_summary(self, state_label: str) -> str:
        lines = ["■ 要件", f"- 推定意図: {state_label or '不明'}", "", "■ 直近の会話"]
        if not self.recent_dialogue:
            lines.append("- (直近ログなし)")
        else:
            for role, text in self.recent_dialogue:
                lines.append(f"- {role}: {text}")
        return "\n".join(lines)

    def _get_effective_call_id(self, addr: Optional[Tuple[str, int]] = None) -> Optional[str]:
        """
        RTP受信時に有効なcall_idを決定する。
        
        :param addr: RTP送信元のアドレス (host, port)。Noneの場合は既存のロジックを使用
        :return: 有効なcall_id、見つからない場合はNone
        """
        # アドレスが指定されている場合は、アドレス紐づけを優先
        if addr and hasattr(self, '_call_addr_map') and addr in self._call_addr_map:
            return self._call_addr_map[addr]
        
        # すでにアクティブ通話が1件のみの場合はそれを使う
        if hasattr(self, '_active_calls') and len(self._active_calls) == 1:
            return next(iter(self._active_calls))
        
        # アクティブな通話がある場合は最後に開始された通話を使用
        if hasattr(self, '_active_calls') and self._active_calls:
            active = list(self._active_calls)
            if active:
                return active[-1]  # 最後に開始された通話を使用
        
        # 既存のロジック（call_idが未設定の場合は正式なcall_idを生成）
        if not self.call_id:
            # call_idが未設定の場合は正式なcall_idを生成
            if self.client_id:
                self.call_id = self.console_bridge.issue_call_id(self.client_id)
                self.logger.debug(f"Generated call_id: {self.call_id}")
                # AICoreにcall_idを設定
                if self.call_id:
                    self.ai_core.set_call_id(self.call_id)
            else:
                # client_idが未設定の場合はデフォルト値を使用（警告を出さない）
                effective_client_id = self.default_client_id or "000"
                self.call_id = self.console_bridge.issue_call_id(effective_client_id)
                self.logger.debug(f"Generated call_id: {self.call_id} using default client_id={effective_client_id}")
                # AICoreにcall_idを設定
                if self.call_id:
                    self.ai_core.set_call_id(self.call_id)
                    # client_idも設定
                    self.client_id = effective_client_id
                    self.logger.debug(f"Set client_id to default: {effective_client_id}")
        
        return self.call_id
    
    def _maybe_send_audio_level(self, rms: int) -> None:
        """RMS値を正規化して、一定間隔で音量レベルを管理画面に送信。"""
        if not self.console_bridge.enabled or not self.call_id:
            return
        
        now = time.time()
        # RMSを0.0〜1.0に正規化
        normalized_level = min(1.0, rms / self.RMS_MAX)
        
        # 送信間隔チェック
        time_since_last = now - self.last_audio_level_time
        if time_since_last < self.AUDIO_LEVEL_INTERVAL:
            return
        
        # レベル変化が小さい場合は送らない（スパム防止）
        level_diff = abs(normalized_level - self.last_audio_level_sent)
        if level_diff < self.AUDIO_LEVEL_THRESHOLD and normalized_level < 0.1:
            return
        
        # 送信
        self.console_bridge.send_audio_level(
            self.call_id,
            normalized_level,
            direction="user",
            client_id=self.client_id,
        )
        self.last_audio_level_sent = normalized_level
        self.last_audio_level_time = now

    def _complete_console_call(self) -> None:
        if not self.console_bridge.enabled or not self.call_id or self.call_completed:
            return
        call_id_to_complete = self.call_id
        self.console_bridge.complete_call(call_id_to_complete, ended_at=datetime.utcnow())
        # ストリーミングモード: call_idの状態をリセット
        if self.streaming_enabled:
            self.ai_core.reset_call(call_id_to_complete)
        # アクティブな通話から削除
        if hasattr(self, '_active_calls'):
            self._active_calls.discard(call_id_to_complete)
        # 通話終了時の状態クリーンアップ
        self._last_voice_time.pop(call_id_to_complete, None)
        self._last_silence_time.pop(call_id_to_complete, None)
        self._last_tts_end_time.pop(call_id_to_complete, None)
        self._last_user_input_time.pop(call_id_to_complete, None)
        self._silence_warning_sent.pop(call_id_to_complete, None)
        if hasattr(self, '_initial_tts_sent'):
            self._initial_tts_sent.discard(call_id_to_complete)
        self.logger.debug(f"[CALL_CLEANUP] Cleared state for call_id={call_id_to_complete}")
        self.call_completed = True
        self.call_id = None
        self.recent_dialogue.clear()
        self.transfer_notified = False
        # 音量レベル送信もリセット
        self.last_audio_level_sent = 0.0
        self.last_audio_level_time = 0.0
        # 補正用の変数もリセット
        self.user_turn_index = 0
        self.call_start_time = None
        self._reset_call_state()

    def _load_wav_as_ulaw8k(self, wav_path: Path) -> bytes:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if n_channels > 1:
            frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
        if sample_width != 2:
            frames = audioop.lin2lin(frames, sample_width, 2)
            sample_width = 2
        if framerate != 8000:
            frames, _ = audioop.ratecv(frames, sample_width, 1, framerate, 8000, None)
        return audioop.lin2ulaw(frames, sample_width)

    def _queue_initial_audio_sequence(self, client_id: Optional[str]) -> None:
        if self.initial_sequence_played:
            return

        effective_client_id = client_id or self.default_client_id
        if not effective_client_id:
            return

        # 無音監視基準時刻を初期化（通話開始時）
        effective_call_id = self._get_effective_call_id()
        if effective_call_id:
            current_time = time.monotonic()
            self._last_tts_end_time[effective_call_id] = current_time
            self._last_user_input_time[effective_call_id] = current_time
            # アクティブな通話として登録
            self._active_calls.add(effective_call_id)
            self.logger.debug(
                f"[CALL_START] Initialized silence monitoring timestamps for call_id={effective_call_id}"
            )

        try:
            audio_paths = self.audio_manager.play_incoming_sequence(effective_client_id)
        except Exception as e:
            self.logger.error(f"[client={effective_client_id}] Failed to load incoming sequence: {e}")
            return
        
        if audio_paths:
            self.logger.info(
                "[client=%s] initial greeting files=%s",
                effective_client_id,
                [str(p) for p in audio_paths],
            )
        else:
            self.logger.warning(f"[client={effective_client_id}] No audio files found for initial sequence")

        chunk_size = 160
        queued_chunks = 0
        queue_labels = []

        # 1) 0.5秒の無音を000よりも前に必ず積む（RTP開始時のノイズ防止）
        silence_payload = self._generate_silence_ulaw(self.initial_silence_sec)
        silence_samples = len(silence_payload)
        silence_chunks = 0
        for i in range(0, len(silence_payload), chunk_size):
            self.tts_queue.append(silence_payload[i : i + chunk_size])
            silence_chunks += 1
            queued_chunks += 1
        if silence_chunks:
            queue_labels.append(f"silence({self.initial_silence_sec:.1f}s)")
            self.logger.info(
                "[client=%s] initial silence queued samples=%d chunks=%d duration=%.3fs",
                effective_client_id,
                silence_samples,
                silence_chunks,
                silence_samples / 8000.0,
            )

        file_entries = []
        for audio_path in audio_paths:
            if not audio_path.exists():
                self.logger.warning(f"[client={effective_client_id}] audio file missing: {audio_path}")
                continue
            try:
                ulaw_payload = self._load_wav_as_ulaw8k(audio_path)
            except Exception as e:
                self.logger.error(f"[client={effective_client_id}] failed to prepare {audio_path}: {e}")
                continue
            size = None
            try:
                size = audio_path.stat().st_size
            except OSError:
                size = None
            try:
                rel = str(audio_path.relative_to(_PROJECT_ROOT))
            except ValueError:
                rel = str(audio_path)
            file_entries.append({"path": rel, "size": size})

            queue_labels.append(audio_path.stem)
            # 2) クライアント設定順（例: 000→001→002）に従い各ファイルを順番に積む
            for i in range(0, len(ulaw_payload), chunk_size):
                self.tts_queue.append(ulaw_payload[i : i + chunk_size])
                queued_chunks += 1

        if file_entries:
            self.logger.info("[client=%s] initial greeting files=%s", effective_client_id, file_entries)

        if queue_labels:
            pretty_order = " -> ".join(queue_labels)
            pretty_paths = " -> ".join(str(p) for p in audio_paths) or "n/a"
            self.logger.info(
                "[client=%s] initial queue order=%s (paths=%s)",
                effective_client_id,
                pretty_order,
                pretty_paths,
            )

        if queued_chunks:
            self.is_speaking_tts = True
            self.initial_sequence_played = True
            self.initial_sequence_playing = True  # 初回シーケンス再生中フラグを立てる
            self.logger.info(
                "[INITIAL_SEQUENCE] ON: client=%s initial_sequence_playing=True (ASR will be disabled during playback)",
                effective_client_id
            )
            self.logger.info(
                "[client=%s] initial greeting enqueued (%d chunks)", effective_client_id, queued_chunks
            )

    def _generate_silence_ulaw(self, duration_sec: float) -> bytes:
        samples = max(1, int(8000 * duration_sec))
        pcm16_silence = b"\x00\x00" * samples
        return audioop.lin2ulaw(pcm16_silence, 2)
    
    def _start_recording(self) -> None:
        """録音を開始する"""
        if not self.recording_enabled or self.recording_file is not None:
            return
        
        try:
            recordings_dir = Path("/opt/libertycall/recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)
            
            # ファイル名を生成（call_id またはタイムスタンプ）
            call_id_str = self.call_id or "unknown"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"call_{call_id_str}_{timestamp}.wav"
            self.recording_path = recordings_dir / filename
            
            # WAVファイルを開く（8kHz, 16bit, モノラル）
            self.recording_file = wave.open(str(self.recording_path), 'wb')
            self.recording_file.setnchannels(1)  # モノラル
            self.recording_file.setsampwidth(2)   # 16bit = 2 bytes
            self.recording_file.setframerate(8000)  # 8kHz
            
            self.logger.info(
                f"録音開始: call_id={call_id_str} path={self.recording_path}"
            )
        except Exception as e:
            self.logger.error(f"録音開始エラー: {e}", exc_info=True)
            self.recording_file = None
            self.recording_path = None
    
    def _stop_recording(self) -> None:
        """録音を停止する"""
        if self.recording_file is not None:
            try:
                self.recording_file.close()
                self.logger.info(
                    f"録音停止: path={self.recording_path}"
                )
            except Exception as e:
                self.logger.error(f"録音停止エラー: {e}", exc_info=True)
            finally:
                self.recording_file = None
                self.recording_path = None

    def _reset_call_state(self) -> None:
        was_playing = self.initial_sequence_playing
        self.initial_sequence_played = False
        self.initial_sequence_playing = False  # 初回シーケンス再生中フラグもリセット
        if was_playing:
            self.logger.info("[INITIAL_SEQUENCE] OFF: call state reset (initial_sequence_playing=False)")
        self.tts_queue.clear()
        self.is_speaking_tts = False
        self.audio_buffer = bytearray()
        self.current_segment_start = None
        self.is_user_speaking = False
        self.last_voice_time = time.time()
        self.rtp_peer = None
        self.rtp_packet_count = 0
        self.last_rtp_packet_time = 0.0
        self._last_tts_text = None  # 直前のTTSテキストもリセット
        
        # ストリーミングモード用変数もリセット
        self._stream_chunk_counter = 0
        self._last_feed_time = time.time()
        
        # ★ call_id関連をリセット（新しい通話の識別のため）
        old_call_id = self.call_id
        self.call_id = None
        self.call_start_time = None
        self.user_turn_index = 0
        self.call_completed = False
        self.transfer_notified = False
        self.recent_dialogue.clear()
        
        # 無音検出用変数もリセット
        if old_call_id:
            self._last_user_input_time.pop(old_call_id, None)
            self._last_tts_end_time.pop(old_call_id, None)
            self._no_input_elapsed.pop(old_call_id, None)
            if old_call_id in self._no_input_timers:
                timer_task = self._no_input_timers.pop(old_call_id)
                if timer_task and not timer_task.done():
                    timer_task.cancel()
        
        # AICoreのcall_idもリセット
        if hasattr(self.ai_core, 'set_call_id'):
            self.ai_core.set_call_id(None)
        if hasattr(self.ai_core, 'call_id'):
            self.ai_core.call_id = None
        if hasattr(self.ai_core, 'log_session_id'):
            self.ai_core.log_session_id = None
        
        if old_call_id:
            self.logger.info(f"[RESET_CALL_STATE] call_id reset: {old_call_id} -> None")
        
        # 録音を停止
        self._stop_recording()

    async def _process_streaming_transcript(
        self, text: str, audio_duration: float, inference_time: float, end_to_text_delay: float
    ):
        """
        ストリーミングモード: 確定した発話テキストを処理する（AIロジック実行）。
        
        :param text: 認識されたテキスト
        :param audio_duration: 音声長（秒）
        :param inference_time: 推論時間（秒）
        :param end_to_text_delay: 発話終了からテキスト確定までの遅延（秒）
        """
        # 初回シーケンス再生中は ASR/TTS をブロック（000→001→002 が必ず流れるように）
        if self.initial_sequence_playing:
            return
        
        if not text:
            return
        
        # 幻聴フィルター（AICoreのロジックを再利用）
        if self.ai_core._is_hallucination(text):
            self.logger.debug(">> Ignored hallucination (noise)")
            return
        
        # ユーザー発話のturn_indexをインクリメント
        self.user_turn_index += 1
        
        # 通話開始からの経過時間を計算
        elapsed_from_call_start_ms = 0
        if self.call_start_time is not None:
            elapsed_from_call_start_ms = int((time.time() - self.call_start_time) * 1000)
        
        # テキスト正規化（「もしもし」補正など）
        effective_call_id = self._get_effective_call_id()
        raw_text = text
        normalized_text, rule_applied = normalize_transcript(
            effective_call_id,
            raw_text,
            self.user_turn_index,
            elapsed_from_call_start_ms
        )
        
        # ログ出力（常にINFOで出力）
        self.logger.info(f"ASR_RAW: '{raw_text}'")
        if rule_applied:
            self.logger.info(f"ASR_NORMALIZED: '{normalized_text}' (rule={rule_applied})")
        else:
            self.logger.info(f"ASR_NORMALIZED: '{normalized_text}' (rule=NONE)")
        
        # 以降は正規化されたテキストを使用
        text = normalized_text
        
        # ユーザー発話時刻を記録（無音検出用、time.monotonic()で統一）
        now = time.monotonic()
        self._last_user_input_time[effective_call_id] = now
        # no_input_streakをリセット（ユーザーが発話したので）
        state = self.ai_core._get_session_state(effective_call_id)
        caller_number = getattr(self.ai_core, "caller_number", None) or "未設定"
        
        # 【デバッグ】音声アクティビティ検知
        detected_speech = bool(text and text.strip())
        self.logger.debug(
            f"[on_audio_activity] call_id={effective_call_id}, detected_speech={detected_speech}, "
            f"text={text[:30] if text else 'None'}, resetting_timer"
        )
        
        # 音声が受信された際に無音検知タイマーをリセットして再スケジュール
        if detected_speech:
            self.logger.debug(f"[on_audio_activity] Resetting no_input_timer for call_id={effective_call_id}")
            await self._start_no_input_timer(effective_call_id)
        
        if text.strip() in self.NO_INPUT_SILENT_PHRASES:
            self.logger.info(
                f"[NO_INPUT] call_id={effective_call_id} caller={caller_number} reset by filler '{text.strip()}'"
            )
            state.no_input_streak = 0
            self._no_input_elapsed[effective_call_id] = 0.0
        elif state.no_input_streak > 0:
            self.logger.info(
                f"[NO_INPUT] call_id={effective_call_id} caller={caller_number} streak reset (user input detected: {text[:30]})"
            )
            state.no_input_streak = 0
            self._no_input_elapsed[effective_call_id] = 0.0
        
        # 意図判定と返答生成（従来のprocess_dialogueのロジックを再利用）
        from libertycall.gateway.intent_rules import classify_intent, get_response_template
        
        intent = classify_intent(text)
        self.logger.debug(f"Intent: {intent}")
        
        if intent == "IGNORE":
            return
        
        resp_text = get_response_template(intent)
        should_transfer = (intent in ["HUMAN", "UNKNOWN"])
        
        # 状態更新
        state_label = (intent or self.current_state).lower()
        self.current_state = state_label
        self._record_dialogue("ユーザー", text)
        self._append_console_log("user", text, state_label)
        
        if resp_text:
            self._record_dialogue("AI", resp_text)
            self._append_console_log("ai", resp_text, self.current_state)
        
        # TTS生成
        tts_audio_24k = None
        if self.ai_core.tts_client and self.ai_core.voice_params and self.ai_core.audio_config:
            synthesis_input = texttospeech.SynthesisInput(text=resp_text)
            response = self.ai_core.tts_client.synthesize_speech(
                input=synthesis_input,
                voice=self.ai_core.voice_params,
                audio_config=self.ai_core.audio_config
            )
            tts_audio_24k = response.audio_content
        
        # TTSキューに追加
        if tts_audio_24k:
            ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
            chunk_size = 160
            for i in range(0, len(ulaw_response), chunk_size):
                self.tts_queue.append(ulaw_response[i:i+chunk_size])
            self.logger.debug(f">> TTS Queued")
            self.is_speaking_tts = True
        
        # 転送処理
        if should_transfer:
            self.logger.info(f">> TRANSFER REQUESTED to {OPERATOR_NUMBER}")
            # 転送処理を実行
            effective_call_id = self._get_effective_call_id()
            self._handle_transfer(effective_call_id)
        
        # ログ出力（発話長、推論時間、遅延時間）
        # ★ turn_id管理: ストリーミングモードでのユーザー発話カウンター（非ストリーミングモードと統一）
        text_norm = normalize_text(text) if text else ""
        self.logger.info(
            f"STREAMING_TURN {self.turn_id}: "
            f"audio={audio_duration:.2f}s / infer={inference_time:.3f}s / "
            f"delay={end_to_text_delay:.3f}s -> '{text_norm}' (intent={intent})"
        )
        self.turn_id += 1

    async def _start_no_input_timer(self, call_id: str) -> None:
        """
        無音検知タイマーを起動する（async対応版、既存タスクがあればキャンセルして再起動）
        """
        try:
            existing = self._no_input_timers.pop(call_id, None)
            if existing and not existing.done():
                existing.cancel()
                self.logger.debug(f"[DEBUG_INIT] Cancelled existing no_input_timer for call_id={call_id}")

            now = time.monotonic()
            self._last_user_input_time[call_id] = now
            self._last_tts_end_time[call_id] = now
            self._no_input_elapsed[call_id] = 0.0

            async def _timer():
                try:
                    await asyncio.sleep(self.NO_INPUT_TIMEOUT)
                    if not self.running:
                        return
                    await self._handle_no_input_timeout(call_id)
                except asyncio.CancelledError:
                    self.logger.debug(f"[DEBUG_INIT] no_input_timer cancelled for call_id={call_id}")
                finally:
                    self._no_input_timers.pop(call_id, None)

            task = asyncio.create_task(_timer())
            self._no_input_timers[call_id] = task
            self.logger.debug(
                f"[DEBUG_INIT] no_input_timer started for call_id={call_id} "
                f"(timeout={self.NO_INPUT_TIMEOUT}s, task={task}, done={task.done()}, cancelled={task.cancelled()})"
            )
            self.logger.info(
                f"[DEBUG_INIT] no_input_timer started for call_id={call_id} "
                f"(timeout={self.NO_INPUT_TIMEOUT}s, task_done={task.done()}, task_cancelled={task.cancelled()})"
            )
        except Exception as e:
            self.logger.exception(f"[NO_INPUT] Failed to start no_input_timer for call_id={call_id}: {e}")

    async def _no_input_monitor_loop(self):
        """無音状態を監視し、自動ハングアップを行う"""
        self.logger.info("NO_INPUT_MONITOR_LOOP: started")
        
        while self.running:
            try:
                now = time.monotonic()
                
                # _active_calls が存在しない場合は初期化
                if not hasattr(self, '_active_calls'):
                    self._active_calls = set()
                
                # 現在アクティブな通話を走査
                active_call_ids = list(self._active_calls) if self._active_calls else []
                
                # アクティブな通話がない場合は待機
                if not active_call_ids:
                    await asyncio.sleep(1.0)
                    continue
                
                # 各アクティブな通話について無音検出を実行
                for call_id in active_call_ids:
                    try:
                        # 最後に有音を検出した時刻を取得
                        last_voice = self._last_voice_time.get(call_id, 0)
                        
                        # 最後に有音を検出した時刻が0の場合は、TTS送信完了時刻を使用
                        if last_voice == 0:
                            last_voice = self._last_tts_end_time.get(call_id, now)
                        
                        # 無音継続時間を計算
                        elapsed = now - last_voice
                        
                        # TTS送信中は無音検出をスキップ
                        if self.is_speaking_tts:
                            continue
                        
                        # 初回シーケンス再生中は無音検出をスキップ
                        if self.initial_sequence_playing:
                            continue
                        
                        # 無音5秒ごとに警告ログ出力
                        if elapsed > 5 and abs(elapsed % 5) < 1:
                            self.logger.warning(
                                f"[SILENCE DETECTED] {elapsed:.1f}s of silence call_id={call_id}"
                            )
                        
                        # 警告送信済みセットを初期化（存在しない場合）
                        if call_id not in self._silence_warning_sent:
                            self._silence_warning_sent[call_id] = set()
                        
                        warnings = self._silence_warning_sent[call_id]
                        
                        # 段階的な無音警告（5秒、10秒、15秒）とアナウンス再生
                        if elapsed >= 5.0 and 5.0 not in warnings:
                            warnings.add(5.0)
                            self.logger.warning(f"[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}")
                            await self._play_silence_warning(call_id, 5.0)
                        elif elapsed >= 10.0 and 10.0 not in warnings:
                            warnings.add(10.0)
                            self.logger.warning(f"[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}")
                            await self._play_silence_warning(call_id, 10.0)
                        elif elapsed >= 15.0 and 15.0 not in warnings:
                            warnings.add(15.0)
                            self.logger.warning(f"[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}")
                            await self._play_silence_warning(call_id, 15.0)
                        
                        # 無音が規定時間を超えたら強制切断
                        max_silence_time = getattr(self, "SILENCE_HANGUP_TIME", 20.0)
                        if elapsed > max_silence_time:
                            self.logger.warning(
                                f"[AUTO-HANGUP] Silence limit exceeded ({elapsed:.1f}s) call_id={call_id}"
                            )
                            
                            # console_bridge に無音切断イベントを記録
                            # 注意: enabled チェックは record_event() 内で行わない（ファイル記録のため常に実行）
                            try:
                                caller_number = getattr(self.ai_core, "caller_number", None) or "unknown"
                                self.console_bridge.record_event(
                                    call_id,
                                    "auto_hangup_silence",
                                    {
                                        "elapsed": elapsed,
                                        "caller": caller_number,
                                        "max_silence_time": max_silence_time,
                                    }
                                )
                                self.logger.info(
                                    f"[AUTO-HANGUP] Event recorded: call_id={call_id} elapsed={elapsed:.1f}s"
                                )
                            except Exception as e:
                                self.logger.error(
                                    f"[AUTO-HANGUP] Failed to record event for call_id={call_id}: {e}",
                                    exc_info=True
                                )
                            
                            try:
                                # 非同期タスクとして実行（既存の同期関数を呼び出す）
                                loop = asyncio.get_running_loop()
                                loop.run_in_executor(None, self._handle_hangup, call_id)
                            except Exception as e:
                                self.logger.exception(f"[AUTO-HANGUP] Hangup failed call_id={call_id} error={e}")
                            # 警告セットをクリア（次の通話のために）
                            self._silence_warning_sent.pop(call_id, None)
                            continue
                        
                        # 音声が検出された場合は警告セットをリセット
                        if elapsed < 1.0:  # 1秒以内に音声が検出された場合
                            if call_id in self._silence_warning_sent:
                                self._silence_warning_sent[call_id].clear()
                    except Exception as e:
                        self.logger.exception(f"NO_INPUT_MONITOR_LOOP error for call_id={call_id}: {e}")
                
            except Exception as e:
                self.logger.exception(f"NO_INPUT_MONITOR_LOOP error: {e}")
            
            await asyncio.sleep(1.0)  # 1秒間隔でチェック
    
    async def _play_tts(self, call_id: str, text: str):
        """TTS音声を再生する"""
        self.logger.info(f"[PLAY_TTS] dispatching text='{text}' to TTS queue for {call_id}")
        try:
            self._send_tts(call_id, text, None, False)
        except Exception as e:
            self.logger.error(f"TTS playback failed for call_id={call_id}: {e}", exc_info=True)
    
    async def _play_silence_warning(self, call_id: str, warning_interval: float):
        """
        無音時に流すアナウンス
        
        :param call_id: 通話ID
        :param warning_interval: 警告間隔（5.0, 10.0, 15.0）
        """
        try:
            # 警告間隔に応じてメッセージを変更
            text_map = {
                5.0: "もしもし？お話がない場合は通話を終了します。",
                10.0: "もしもし？お聞き取りできていますか？",
                15.0: "お話がない場合は、まもなく通話を終了します。"
            }
            text = text_map.get(warning_interval, "もしもし？お話がない場合は通話を終了します。")
            
            self.logger.info(f"[SILENCE_WARNING] call_id={call_id} interval={warning_interval:.0f}s text={text!r}")
            await self._play_tts(call_id, text)
        except Exception as e:
            self.logger.error(f"Silence warning playback failed for call_id={call_id}: {e}", exc_info=True)
    
    async def _wait_for_no_input_reset(self, call_id: str):
        """
        無音タイムアウト処理後、次のタイムアウトまで待機する
        """
        await asyncio.sleep(self.NO_INPUT_TIMEOUT + 1.0)  # タイムアウト時間 + 1秒待機
        # タイマーをクリア（次のタイムアウトを許可）
        if call_id in self._no_input_timers:
            del self._no_input_timers[call_id]
    
    async def _handle_no_input_timeout(self, call_id: str):
        """
        無音タイムアウトを処理: NOT_HEARD intentをai_coreに渡す
        
        :param call_id: 通話ID
        """
        try:
            # 【デバッグ】無音タイムアウト発火
            state = self.ai_core._get_session_state(call_id)
            streak_before = state.no_input_streak
            streak = min(streak_before + 1, self.NO_INPUT_STREAK_LIMIT)
            
            # 明示的なデバッグログを追加
            self.logger.debug(f"[NO_INPUT] Triggered for call_id={call_id}, streak={streak}")
            self.logger.info(f"[NO_INPUT] Triggered for call_id={call_id}, streak={streak}")
            
            # 発信者番号を取得（ログ出力用）
            caller_number = getattr(self.ai_core, "caller_number", None) or "未設定"
            self.logger.debug(f"[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}")
            self.logger.info(
                f"[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}"
            )
            
            # ai_coreの状態を取得
            no_input_streak = streak
            state.no_input_streak = no_input_streak
            # 無音経過時間を累積
            elapsed = self._no_input_elapsed.get(call_id, 0.0) + self.NO_INPUT_TIMEOUT
            self._no_input_elapsed[call_id] = elapsed
            
            self.logger.debug(f"[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} elapsed={elapsed:.1f}s (incrementing)")
            self.logger.info(
                f"[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} elapsed={elapsed:.1f}s (incrementing)"
            )
            
            # NOT_HEARD intentとして処理（空のテキストで呼び出す）
            # ai_core側でno_input_streakに基づいてテンプレートを選択する
            reply_text = self.ai_core.on_transcript(call_id, "", is_final=True)
            
            if reply_text:
                # TTS送信（テンプレートIDはai_core側で決定される）
                template_ids = state.last_ai_templates if hasattr(state, 'last_ai_templates') else []
                self._send_tts(call_id, reply_text, template_ids, False)
                
                # テンプレート112の場合は自動切断を予約（ai_core側で処理される）
                if "112" in template_ids:
                    self.logger.info(
                        f"[NO_INPUT] call_id={call_id} template=112 detected, auto_hangup will be scheduled"
                    )
            
            # 最大無音時間を超えた場合は強制切断を実行（管理画面でも把握しやすいよう詳細ログ）
            if self._no_input_elapsed.get(call_id, 0.0) >= self.MAX_NO_INPUT_TIME:
                elapsed_total = self._no_input_elapsed.get(call_id, 0.0)
                self.logger.debug(
                    f"[NO_INPUT] call_id={call_id} caller={caller_number} exceeded MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s "
                    f"(streak={no_input_streak}, elapsed={elapsed_total:.1f}s) -> FORCE_HANGUP"
                )
                self.logger.warning(
                    f"[NO_INPUT] call_id={call_id} caller={caller_number} exceeded MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s "
                    f"(streak={no_input_streak}, elapsed={elapsed_total:.1f}s) -> FORCE_HANGUP"
                )
                # 直前の状態を詳細ログに出力（原因追跡用）
                self.logger.debug(
                    f"[FORCE_HANGUP] Preparing disconnect: call_id={call_id} caller={caller_number} "
                    f"elapsed={elapsed_total:.1f}s streak={no_input_streak} max_timeout={self.MAX_NO_INPUT_TIME}s"
                )
                self.logger.warning(
                    f"[FORCE_HANGUP] Preparing disconnect: call_id={call_id} caller={caller_number} "
                    f"elapsed={elapsed_total:.1f}s streak={no_input_streak} max_timeout={self.MAX_NO_INPUT_TIME}s"
                )
                self.logger.debug(
                    f"[FORCE_HANGUP] Attempting to disconnect call_id={call_id} after {elapsed_total:.1f}s of silence "
                    f"(streak={no_input_streak}, timeout={self.MAX_NO_INPUT_TIME}s)"
                )
                self.logger.info(
                    f"[FORCE_HANGUP] Attempting to disconnect call_id={call_id} after {elapsed_total:.1f}s of silence "
                    f"(streak={no_input_streak}, timeout={self.MAX_NO_INPUT_TIME}s)"
                )
                # 1分無音継続時は強制切断をスケジュール（確実に実行）
                try:
                    if hasattr(self.ai_core, "_schedule_auto_hangup"):
                        self.ai_core._schedule_auto_hangup(call_id, delay_sec=1.0)
                        self.logger.info(
                            f"[NO_INPUT] FORCE_HANGUP_SCHEDULED: call_id={call_id} caller={caller_number} "
                            f"elapsed={elapsed_total:.1f}s delay=1.0s"
                        )
                    elif self.ai_core.hangup_callback:
                        # _schedule_auto_hangupが存在しない場合は直接コールバックを呼び出す
                        self.logger.info(
                            f"[NO_INPUT] FORCE_HANGUP_DIRECT: call_id={call_id} caller={caller_number} "
                            f"elapsed={elapsed_total:.1f}s (no _schedule_auto_hangup method)"
                        )
                        self.ai_core.hangup_callback(call_id)
                    else:
                        self.logger.error(
                            f"[NO_INPUT] FORCE_HANGUP_FAILED: call_id={call_id} caller={caller_number} "
                            f"hangup_callback not set"
                        )
                except Exception as e:
                    self.logger.exception(
                        f"[NO_INPUT] FORCE_HANGUP_ERROR: call_id={call_id} caller={caller_number} error={e!r}"
                    )
                # 強制切断後は処理を終了
                return
            
        except Exception as e:
            self.logger.exception(f"[NO_INPUT] Error handling timeout for call_id={call_id}: {e}")

    async def _log_monitor_loop(self):
        """
        ログファイルを監視し、HANDOFF_FAIL_TTS_REQUESTメッセージを検出してTTSアナウンスを送信
        """
        self.logger.debug("Log monitor loop started.")
        log_file = Path("/opt/libertycall/logs/realtime_gateway.log")
        processed_lines = set()  # 処理済みの行を記録（重複防止）
        
        # ログファイルが存在しない場合は作成を待つ
        if not log_file.exists():
            self.logger.warning("Gateway log file not found, waiting for creation...")
            while not log_file.exists() and self.running:
                await asyncio.sleep(1)
        
        # 起動時は現在のファイルサイズから開始（過去のログを読み込まない）
        if log_file.exists():
            last_position = log_file.stat().st_size
            self.logger.debug(f"Log monitor: Starting from position {last_position} (current file size)")
        else:
            last_position = 0
        
        while self.running:
            try:
                if log_file.exists():
                    with open(log_file, "r", encoding="utf-8") as f:
                        # 最後に読み取った位置に移動
                        f.seek(last_position)
                        new_lines = f.readlines()
                        
                        # 新しい行を処理
                        for line in new_lines:
                            # 行のハッシュを計算して重複チェック
                            line_hash = hash(line.strip())
                            if line_hash in processed_lines:
                                continue
                            
                            if "[HANDOFF_FAIL_TTS_REQUEST]" in line:
                                # メッセージをパース
                                # フォーマット: [HANDOFF_FAIL_TTS_REQUEST] call_id=xxx text=xxx audio_len=xxx
                                try:
                                    # call_idとtextを抽出
                                    import re
                                    call_id_match = re.search(r'call_id=([^\s]+)', line)
                                    # text='...' または text="..." の形式を抽出
                                    text_match_quoted = re.search(r"text=([\"'])(.*?)\1", line)
                                    text_match_unquoted = re.search(r'text=([^\s]+)', line)
                                    
                                    if call_id_match:
                                        call_id = call_id_match.group(1)
                                        # 引用符で囲まれたテキストを優先、なければ引用符なしのテキスト
                                        if text_match_quoted:
                                            text = text_match_quoted.group(2)
                                        elif text_match_unquoted:
                                            text = text_match_unquoted.group(1)
                                        else:
                                            self.logger.warning(f"HANDOFF_FAIL_TTS: Failed to extract text from line: {line}")
                                            processed_lines.add(line_hash)
                                            continue
                                        
                                        # 現在の通話でない場合は無視（call_idが一致しない、または通話が開始されていない）
                                        effective_call_id = self._get_effective_call_id()
                                        if call_id != effective_call_id:
                                            self.logger.debug(
                                                f"HANDOFF_FAIL_TTS_SKIP: call_id mismatch (request={call_id}, current={effective_call_id})"
                                            )
                                            processed_lines.add(line_hash)
                                            continue
                                        
                                        # call_idが未設定の場合は正式なcall_idを生成
                                        if not self.call_id:
                                            if self.client_id:
                                                self.call_id = self.console_bridge.issue_call_id(self.client_id)
                                                self.logger.info(
                                                    f"HANDOFF_FAIL_TTS: generated call_id={self.call_id}"
                                                )
                                                # AICoreにcall_idを設定
                                                if self.call_id:
                                                    self.ai_core.set_call_id(self.call_id)
                                            else:
                                                self.logger.debug(
                                                    f"HANDOFF_FAIL_TTS_SKIP: call not started yet (call_id={call_id}, no client_id)"
                                                )
                                                processed_lines.add(line_hash)
                                                continue
                                        
                                        self.logger.info(
                                            f"HANDOFF_FAIL_TTS_DETECTED: call_id={call_id} text={text!r}"
                                        )
                                        
                                        # TTSアナウンスを送信
                                        self._send_tts(call_id, text, None, False)
                                        
                                        # 処理済みとして記録
                                        processed_lines.add(line_hash)
                                        
                                except Exception as e:
                                    self.logger.exception(f"Failed to parse HANDOFF_FAIL_TTS_REQUEST: {e}")
                                    processed_lines.add(line_hash)
                        
                        # 現在の位置を記録
                        last_position = f.tell()
                        
                        # 処理済みセットが大きくなりすぎないように定期的にクリーンアップ
                        if len(processed_lines) > 1000:
                            processed_lines.clear()
                
                # 1秒ごとにチェック
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.exception(f"Log monitor loop error: {e}")
                await asyncio.sleep(1)

class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, gateway: RealtimeGateway):
        self.gateway = gateway
    def connection_made(self, transport):
        self.transport = transport
    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        # 受信フレームを必ずログ（長さと送信元を可視化）
        self.gateway.logger.debug(f"[RTP_RECV_RAW] len={len(data)} from={addr}")
        # UDP 受信を必ずログに記録（Python 側に UDP が届いているか確認用）
        self.gateway.logger.info(
            "RTP_RECV_RAW: from=%s len=%d first_bytes=%s",
            addr,
            len(data),
            data[:4].hex() if len(data) >= 4 else data.hex(),
        )
        try:
            task = asyncio.create_task(self.gateway.handle_rtp_packet(data, addr))
            def log_exception(task: asyncio.Task) -> None:
                exc = task.exception()
                if exc is not None:
                    self.gateway.logger.error(
                        "handle_rtp_packet failed: %r", exc, exc_info=exc
                    )
            task.add_done_callback(log_exception)
        except Exception as e:
            self.gateway.logger.error(
                "Failed to create task for handle_rtp_packet: %r", e, exc_info=True
            )

def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

def setup_logging(level: str = "DEBUG"):
    """Send all logs to stdout (for systemd journal integration)."""
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers (avoid duplicate output)
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    root_logger.addHandler(handler)
    
    # Reduce asyncio log noise
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    logging.debug("[LOG_SETUP] Configured to output logs to stdout (journalctl integration enabled)")

async def main():
    # ログ設定初期化
    setup_logging("DEBUG")

    # 設定読み込み
    config_path = Path(__file__).parent.parent / "config" / "gateway.yaml"
    config = load_config(str(config_path))

    # ログレベル再設定（オプション）
    log_level = config.get("logging", {}).get("level", "DEBUG")
    if log_level != "DEBUG":
        setup_logging(log_level)

    gateway = RealtimeGateway(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(gateway.shutdown()))

    # メイン処理（start() 内で shutdown_event を待つため、ここで常駐）
    await gateway.start()

if __name__ == "__main__":
    asyncio.run(main())