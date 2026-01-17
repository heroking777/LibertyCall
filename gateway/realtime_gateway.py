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
import wave
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict
import yaml
import websockets
import audioop
import collections
import time
import uvicorn
try:
    from scapy.all import sniff, IP, UDP
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
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
from libertycall.gateway.ai_core import AICore
from libertycall.gateway.text_utils import normalize_text
from libertycall.gateway.transcript_normalizer import normalize_transcript
from libertycall.gateway.asr_manager import GatewayASRManager
from libertycall.gateway.playback_manager import GatewayPlaybackManager
from libertycall.gateway.call_session_handler import GatewayCallSessionHandler
from libertycall.gateway.network_manager import GatewayNetworkManager
from libertycall.gateway.monitor_manager import GatewayMonitorManager
from libertycall.gateway.audio_processor import GatewayAudioProcessor
from libertycall.gateway.gateway_utils import GatewayUtils
from libertycall.console_bridge import console_bridge
from gateway.asr_controller import app as asr_app, set_gateway_instance

# Google Streaming ASR統合
try:
    from asr_handler import get_or_create_handler, remove_handler, get_handler
    ASR_HANDLER_AVAILABLE = True
except ImportError:
    ASR_HANDLER_AVAILABLE = False
    get_or_create_handler = None
    remove_handler = None
    get_handler = None

# デバッグ用: AICore のインポート元を確認
logger_debug = logging.getLogger("libertycall.gateway.ai_core")
logger_debug.warning("DEBUG_IMPORT_CHECK: AICore class from %r", AICore.__module__)
logger_debug.warning("DEBUG_IMPORT_CHECK_FILE: ai_core file = %r", AICore.__init__.__code__.co_filename)
try:
    from .audio_manager import AudioManager
except ImportError:  # 実行形式(py gateway/realtime_gateway.py)との両立
    from audio_manager import AudioManager  # type: ignore

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

class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, gateway: 'RealtimeGateway'):
        self.gateway = gateway
        # 受信元アドレスをロックするためのフィールド（最初のパケット送信元を固定）
        self.remote_addr: Optional[Tuple[str, int]] = None
        # 受信元SSRCをロックするためのフィールド（RTPヘッダのbytes 8-11）
        self.remote_ssrc: Optional[int] = None
    def connection_made(self, transport):
        self.transport = transport
        # 【デバッグ強化】実際にバインドされたアドレスとポートを確認
        try:
            sock = transport.get_extra_info('socket')
            if sock:
                bound_addr = sock.getsockname()
                self.gateway.logger.debug(f"DEBUG_TRACE: [RTP_SOCKET] Bound successfully to: {bound_addr}")
            else:
                self.gateway.logger.debug("DEBUG_TRACE: [RTP_SOCKET] Transport created (no socket info available)")
        except Exception as e:
            self.gateway.logger.debug(f"DEBUG_TRACE: [RTP_SOCKET] connection_made error: {e}")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        # 【最優先デバッグ】フィルタリング前の「生」の到達を記録（全パケット）
        if not hasattr(self, '_raw_packet_count'):
            self._raw_packet_count = 0
        self._raw_packet_count += 1
        if self._raw_packet_count % 50 == 1:
            print(f"DEBUG_TRACE: [RTP_RECV_RAW] Received {len(data)} bytes from {addr} (count={self._raw_packet_count})", flush=True)
        
        # --- [DEBUG & FILTER ADDITION START] ---
        # フィルタリング: FreeSWITCH自身のIP（送信パケットのループバック）からのパケットは無視する
        # ログで確認されたFreeSWITCHのIP: 160.251.170.253
        # および localhost も念のため除外
        ignore_ips = {'160.251.170.253', '127.0.0.1', '::1'}
        
        if addr[0] in ignore_ips:
            # FreeSWITCH自身からのパケット（システム音声の逆流）を無視
            if self._raw_packet_count % 100 == 1:
                print(f"DEBUG_TRACE: [RTP_FILTER] Ignored packet from local IP: {addr[0]} (count={self._raw_packet_count})", flush=True)
            return
        
        # デバッグ: ユーザーからのパケットのみ処理されることを確認（50回に1回出力）
        if not hasattr(self, '_packet_count'):
            self._packet_count = 0
        self._packet_count += 1
        if self._packet_count % 50 == 1:
            print(f"DEBUG_TRACE: RTPProtocol packet from user IP={addr[0]} port={addr[1]} len={len(data)} count={self._packet_count}", flush=True)
        # --- [DEBUG & FILTER ADDITION END] ---
        
        # 【追加】SSRCフィルタリング（優先）および送信元IP/Portの検証（混線防止）
        try:
            # ヘッダサイズチェック
            if len(data) >= 12:
                try:
                    ssrc = struct.unpack('!I', data[8:12])[0]
                except Exception:
                    ssrc = None
            else:
                ssrc = None

            # SSRCによるロック（存在すれば優先的にチェック）
            if ssrc is not None:
                if self.remote_ssrc is None:
                    self.remote_ssrc = ssrc
                    # IPも記録しておく
                    self.remote_addr = addr
                    self.gateway.logger.info(f"[RTP_FILTER] Locked SSRC={ssrc} from {addr}")
                elif self.remote_ssrc != ssrc:
                    # 異なるSSRCは混入と見なし破棄
                    self.gateway.logger.debug(f"[RTP_FILTER] Ignored packet with SSRC={ssrc} (expected {self.remote_ssrc}) from {addr}")
                    return
            else:
                # SSRC取得できなかった場合はIP/Portで保護（後方互換）
                if self.remote_addr is None:
                    self.remote_addr = addr
                    self.gateway.logger.info(f"[RTP_FILTER] Locked remote address to {addr}")
                elif self.remote_addr != addr:
                    self.gateway.logger.debug(f"[RTP_FILTER] Ignored packet from {addr} (expected {self.remote_addr})")
                    return
        except Exception:
            # フィルタ処理は安全に失敗させない（ログ出力のみ）
            try:
                self.gateway.logger.exception("[RTP_FILTER] Exception while filtering packet")
            except Exception:
                pass

        # 受信確認ログ（UDPパケットが実際に届いているか確認用）
        self.gateway.logger.debug(f"[RTP_RECV] Received {len(data)} bytes from {addr}")
        # RTP受信ログ（軽量版：fromとlenのみ）
        self.gateway.logger.info(f"[RTP_RECV_RAW] from={addr}, len={len(data)}")
        
        # RakutenのRTP監視対策：受信したパケットをそのまま送り返す（エコー）
        # これによりRakuten側は「RTP到達OK」と判断し、通話が切れなくなる
        try:
            if self.transport:
                self.transport.sendto(data, addr)
                self.gateway.logger.debug(f"[RTP_ECHO] sent echo packet to {addr}, len={len(data)}")
        except Exception as e:
            self.gateway.logger.warning(f"[RTP_ECHO] failed to send echo: {e}")
        
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

class ESLAudioReceiver:
    """FreeSWITCHのESL経由でデコード済み音声を受信"""
    
    def __init__(self, call_id, uuid, gateway, logger):
        self.call_id = call_id
        self.uuid = uuid
        self.gateway = gateway
        self.logger = logger
        self.running = False
        self.thread = None
        self.conn = None
        
    def start(self):
        """ESL接続と音声受信を開始"""
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        self.logger.info(f"[ESL_AUDIO] Started for call_id={self.call_id}, uuid={self.uuid}")
        
    def _receive_loop(self):
        """ESLイベントループ（別スレッド）"""
        try:
            from libs.esl.ESL import ESLconnection
            
            self.conn = ESLconnection('127.0.0.1', '8021', 'ClueCon')
            
            if not self.conn.connected():
                self.logger.error(f"[ESL_AUDIO] Failed to connect to FreeSWITCH ESL")
                return
            
            self.conn.events('plain', 'CHANNEL_AUDIO')
            self.conn.filter('Unique-ID', self.uuid)
            
            self.logger.info(f"[ESL_AUDIO] Connected and subscribed to UUID={self.uuid}")
            
            while self.running:
                event = self.conn.recvEventTimed(100)
                
                if not event:
                    continue
                
                event_name = event.getHeader('Event-Name')
                
                if event_name == 'CHANNEL_AUDIO':
                    audio_data = event.getBody()
                    
                    if audio_data:
                        self.gateway.handle_rtp_packet(self.call_id, audio_data)
                        
        except Exception as e:
            self.logger.error(f"[ESL_AUDIO] Exception: {e}")
            import traceback
            traceback.print_exc()
            
    def stop(self):
        """ESL受信を停止"""
        self.running = False
        if self.conn:
            self.conn.disconnect()
        self.logger.info(f"[ESL_AUDIO] Stopped for call_id={self.call_id}")
class RealtimeGateway:
    def __init__(self, config: dict, rtp_port_override: Optional[int] = None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        # 起動確認用ログ（修正版が起動したことを示す）
        self.logger.warning("[DEBUG_VERSION] RealtimeGateway initialized with UPDATED LOGGING logic.")
        # デバッグ用パケットカウンター初期化
        self._debug_packet_count = 0
        # RTPパケット重複処理ガード用（各通話ごとの最新シーケンス番号を保持）
        self._last_processed_sequence = {}  # {call_id: sequence_number}
        # 初期アナウンス実行済みフラグ（各通話ごとの初期アナウンス状態を保持）
        self._initial_sequence_played = set()  # {call_id}
        self.rtp_host = config["rtp"]["listen_host"]
        # ポート番号の優先順位: コマンドライン引数 > LC_RTP_PORT > LC_GATEWAY_PORT > gateway.yaml > 固定値 7100
        if rtp_port_override is not None:
            # コマンドライン引数が最優先
            self.rtp_port = rtp_port_override
            self.logger.info(f"[INIT] RTP port overridden by CLI argument: {self.rtp_port}")
        else:
            # 環境変数をチェック
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
        # デフォルトクライアントIDで初期化（後でWebSocket init時に再読み込みされる）
        initial_client_id = os.getenv("LC_DEFAULT_CLIENT_ID", "000")
        self.ai_core = AICore(client_id=initial_client_id)
        self.session_handler = GatewayCallSessionHandler(self)
        self.network_manager = GatewayNetworkManager(self)
        self.audio_processor = GatewayAudioProcessor(self)
        self.utils = GatewayUtils(self, RTPPacketBuilder, RTPProtocol)
        self.monitor_manager = GatewayMonitorManager(
            self,
            RTPProtocol,
            SCAPY_AVAILABLE,
            sniff_func=sniff if SCAPY_AVAILABLE else None,
            ip_cls=IP if SCAPY_AVAILABLE else None,
            udp_cls=UDP if SCAPY_AVAILABLE else None,
            esl_receiver_cls=ESLAudioReceiver,
        )
        # TTS 送信用コールバックを設定
        self.ai_core.tts_callback = self._send_tts
        self.ai_core.transfer_callback = self._handle_transfer
        # 自動切断用コールバックを設定
        self.ai_core.hangup_callback = self._handle_hangup
        # 音声再生用コールバックを設定
        self.ai_core.playback_callback = self._handle_playback
        
        # FreeSWITCH ESL接続を初期化（再生制御・割り込み用）
        self.esl_connection = None
        self._init_esl_connection()
        self.logger.info(
            "HANGUP_CALLBACK_SET: hangup_callback=%s",
            "set" if self.ai_core.hangup_callback else "none"
        )
        
        # call_id -> FreeSWITCH UUID のマッピング
        self.call_uuid_map: Dict[str, str] = {}
        
        # call_uuid_mapへの参照をAICoreに渡す
        self.ai_core.call_uuid_map = self.call_uuid_map
        
        self.audio_processor.initialize_asr_settings(
            asr_handler_available=ASR_HANDLER_AVAILABLE,
            webrtc_available=WEBRTC_NS_AVAILABLE,
            audio_processing_cls=AudioProcessing,
            ns_level_cls=NsLevel,
        )

        # ASRマネージャ初期化
        self.asr_manager = GatewayASRManager(self)
        # Playback/TTSマネージャ初期化
        self.playback_manager = GatewayPlaybackManager(self)
        
        self.audio_buffer = bytearray()          
        self.tts_queue = collections.deque(maxlen=100)  # バッファ拡張（音途切れ防止）
        self.is_speaking_tts = False             
        self.last_voice_time = time.time()
        self.is_user_speaking = False
        
        # 転送処理の遅延実行用
        self._pending_transfer_call_id: Optional[str] = None  # 転送待ちのcall_id
        self._transfer_task_queue = collections.deque()  # イベントループが起動する前の転送タスクキュー 
        
        # FreeSWITCH送信RTPポート監視（pull型ASR用）
        self.fs_rtp_monitor = self.monitor_manager.fs_rtp_monitor
        
        # 調整パラメータ
        self.BARGE_IN_THRESHOLD = 1000 
        self.SILENCE_DURATION = 0.9     # 無音判定 (0.8 -> 0.9)
        self.MAX_SEGMENT_SEC = 2.3      # ★ 最大セグメント長
        self.MIN_AUDIO_LEN = 16000
        self.MIN_RMS_FOR_ASR = 80      # ★ RMS閾値（これ以下のセグメントはASRに送らない）
        self.NO_INPUT_TIMEOUT = 10.0    # 無音10秒で再促し
        self.NO_INPUT_STREAK_LIMIT = 4  # 無音ストリーク上限
        self.MAX_NO_INPUT_TIME = 60.0   # 無音の累積上限（秒）※1分で強制切断を検討
        self.SILENCE_WARNING_INTERVALS = [5.0, 15.0, 25.0]  # 無音警告を送る秒数（5秒、15秒、25秒）
        self.SILENCE_HANGUP_TIME = 60.0  # 無音60秒で自動切断
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
        # 最大通話時間（デフォルト30分）
        self.max_call_duration_sec = float(os.getenv("LC_MAX_CALL_DURATION_SEC", "1800"))
        
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
        # リアルタイム更新用のAPI URL（環境変数から取得、デフォルトはlocalhost:8001）
        self.console_api_url = os.getenv(
            "LIBERTYCALL_CONSOLE_API_BASE_URL",
            "http://localhost:8001"
        )
        self.initial_sequence_played = False
        self.initial_sequence_playing = False  # 初回シーケンス再生中フラグ
        self.initial_sequence_completed = False  # 初回シーケンス完了フラグ
        self.initial_sequence_completed_time: Optional[float] = None
        self._asr_enable_timer: Optional[threading.Timer] = None
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
        self._recovery_counts: Dict[str, int] = {}  # call_id -> RTP_RECOVERY回数（ゾンビ蘇生防止）
        
        # 録音機能の初期化
        self.recording_enabled = os.getenv("LC_ENABLE_RECORDING", "0") == "1"
        self.recording_file: Optional[wave.Wave_write] = None
        self.recording_path: Optional[Path] = None
        if self.recording_enabled:
            recordings_dir = Path("/opt/libertycall/recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"録音機能が有効です。録音ファイルは {recordings_dir} に保存されます。")
        
        # FreeSWITCHイベント受信用Unixソケット
        self.event_socket_path = Path("/tmp/liberty_gateway_events.sock")
        self.event_server: Optional[asyncio.Server] = None

    async def start(self):
        await self.utils.start()

    def _find_rtp_info_by_port(self, rtp_port: int) -> Optional[str]:
        """
        RTP port からファイルを探して UUID を返す
        
        :param rtp_port: RTP port番号
        :return: UUID または None
        """
        return self.utils._find_rtp_info_by_port(rtp_port)

    def _send_tts(
        self,
        call_id: str,
        reply_text: str,
        template_ids: list[str] | None = None,
        transfer_requested: bool = False,
    ) -> None:
        self.playback_manager._send_tts(
            call_id,
            reply_text,
            template_ids=template_ids,
            transfer_requested=transfer_requested,
        )

    async def _flush_tts_queue(self) -> None:
        await self.playback_manager._flush_tts_queue()
    
    async def _send_tts_async(
        self,
        call_id: str,
        reply_text: str | None = None,
        template_ids: list[str] | None = None,
        transfer_requested: bool = False,
    ) -> None:
        await self.playback_manager._send_tts_async(
            call_id,
            reply_text=reply_text,
            template_ids=template_ids,
            transfer_requested=transfer_requested,
        )
    
    def _synthesize_text_sync(self, text: str) -> Optional[bytes]:
        return self.playback_manager._synthesize_text_sync(text)
    
    async def _send_tts_segmented(self, call_id: str, reply_text: str) -> None:
        await self.playback_manager._send_tts_segmented(call_id, reply_text)
    
    def _synthesize_segment_sync(self, segment: str) -> Optional[bytes]:
        return self.playback_manager._synthesize_segment_sync(segment)
    
    async def _wait_for_tts_completion_and_update_time(
        self, call_id: str, tts_audio_length: int
    ) -> None:
        await self.playback_manager._wait_for_tts_completion_and_update_time(
            call_id, tts_audio_length
        )

    async def _wait_for_tts_and_transfer(self, call_id: str, timeout: float = 10.0) -> None:
        await self.playback_manager._wait_for_tts_and_transfer(call_id, timeout=timeout)

    async def _tts_sender_loop(self):
        self.logger.debug("TTS Sender loop started.")
        consecutive_skips = 0
        while self.running:
            # ChatGPT音声風: wakeupイベントがセットされていたら即flush
            if self._tts_sender_wakeup.is_set():
                await self._flush_tts_queue()
                self._tts_sender_wakeup.clear()
            
            if self.tts_queue and self.rtp_transport:
                # FreeSWITCH双方向化: 受信元アドレス（rtp_peer）に送信
                # rtp_peerが設定されていない場合は警告を出してスキップ
                # （rtp_peerは最初のRTPパケット受信時に自動設定される）
                if self.rtp_peer:
                    rtp_dest = self.rtp_peer
                else:
                    # rtp_peerが未設定の場合は送信をスキップ（最初のRTPパケット受信待ち）
                    if consecutive_skips == 0:
                        self.logger.warning("[TTS_SENDER] rtp_peer not set yet, waiting for first RTP packet...")
                    consecutive_skips += 1
                    await asyncio.sleep(0.02)
                    continue
                try:
                    payload = self.tts_queue.popleft()
                    packet = self.rtp_builder.build_packet(payload)
                    self.rtp_transport.sendto(packet, rtp_dest)
                    # 実際に送信したタイミングでログ出力（運用ログ整備）
                    payload_type = packet[1] & 0x7F
                    self.logger.debug(f"[TTS_QUEUE_SEND] sent RTP packet to {rtp_dest}, queue_len={len(self.tts_queue)}, payload_type={payload_type}")
                    # デバッグログ拡張: RTP_SENT（最初のパケットのみ）
                    if not hasattr(self, '_rtp_sent_logged'):
                        self.logger.info(f"[RTP_SENT] {rtp_dest}")
                        self._rtp_sent_logged = True
                    consecutive_skips = 0  # リセット
                except Exception as e:
                    self.logger.error(f"TTS sender failed: {e}", exc_info=True)
            else:
                # キューが空 or 停止状態
                if not self.tts_queue:
                    self.is_speaking_tts = False
                    consecutive_skips = 0
                    # 初回シーケンス再生が完了したらフラグをリセット
                    if self.initial_sequence_playing:
                        # スレッドスイッチを確保してからフラグを変更（非同期ループの確実な実行のため）
                        await asyncio.sleep(0.01)
                        self.initial_sequence_playing = False
                        self.initial_sequence_completed = True
                        self.initial_sequence_completed_time = time.time()
                        self.logger.info(
                            "[INITIAL_SEQUENCE] OFF: initial_sequence_playing=False -> completed=True (ASR enable allowed)"
                        )
            
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
                                        
                                        # クライアントIDが変更された場合、AICoreの会話フローを再読み込み
                                        if hasattr(self.ai_core, 'set_client_id'):
                                            self.ai_core.set_client_id(req_client_id)
                                        elif hasattr(self.ai_core, 'client_id'):
                                            self.ai_core.client_id = req_client_id
                                            if hasattr(self.ai_core, 'reload_flow'):
                                                self.ai_core.reload_flow()
                                        
                                        # caller_numberをAICoreに設定
                                        if req_caller_number:
                                            self.ai_core.caller_number = req_caller_number
                                            self.logger.debug(f"[Init] Set caller_number: {req_caller_number}")
                                        else:
                                            # caller_numberが送られてこない場合はNone（後で"-"として記録される）
                                            self.ai_core.caller_number = None
                                            self.logger.debug("[Init] caller_number not provided in init message")
                                        
                                        self._ensure_console_session(call_id_override=req_call_id)
                                        # 非同期タスクとして実行（結果を待たない）
                                        task = asyncio.create_task(self._queue_initial_audio_sequence(self.client_id))
                                        def _log_init_task_result(t):
                                            try:
                                                t.result()  # 例外があればここで再送出される
                                                # self.logger.warning(f"[INIT_TASK_DONE] Initial sequence task completed successfully.")
                                            except Exception as e:
                                                import traceback
                                                self.logger.error(f"[INIT_TASK_ERR] Initial sequence task failed: {e}\n{traceback.format_exc()}")
                                        task.add_done_callback(_log_init_task_result)
                                        self.logger.warning(f"[INIT_TASK_START] Created task for {self.client_id}")

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
        self.utils._free_port(port)

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
        """
        Asteriskからのinitメッセージを処理（クライアントID自動判定対応）
        """
        await self.session_handler._handle_init_from_asterisk(data)

    def _is_silent_ulaw(self, data: bytes, threshold: float = 0.005) -> bool:
        """
        μ-lawデータをPCMに変換してエネルギー判定を行い、無音かどうかを判定
        
        :param data: μ-lawエンコードされた音声データ
        :param threshold: RMS閾値（デフォルト: 0.005）
        :return: 無音の場合True、有音の場合False
        """
        return self.audio_processor._is_silent_ulaw(data, threshold=threshold)

    def _apply_agc(self, pcm_data: bytes, target_rms: int = 1000) -> bytes:
        """
        Automatic Gain Control: PCM16 データの音量を自動調整して返す
        :param pcm_data: PCM16 リトルエンディアンのバイト列
        :param target_rms: 目標 RMS 値（デフォルト 1000）
        :return: 増幅後の PCM16 バイト列
        """
        return self.audio_processor._apply_agc(pcm_data, target_rms=target_rms)

    async def handle_rtp_packet(self, data: bytes, addr: Tuple[str, int]):
        await self.asr_manager.process_rtp_audio(data, addr)

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
        
        # ASRハンドラーを停止
        if self.call_id and remove_handler:
            try:
                remove_handler(self.call_id)
                self.logger.info(f"[SHUTDOWN] ASR handler removed for call_id={self.call_id}")
            except Exception as e:
                self.logger.warning(f"[SHUTDOWN] Error removing ASR handler: {e}")
        
        # Unixソケットサーバーを停止
        if self.event_server:
            try:
                self.logger.info("[SHUTDOWN] Closing event socket server...")
                self.event_server.close()
                await self.event_server.wait_closed()
                self.logger.info("[SHUTDOWN] Event socket server closed")
            except Exception as e:
                self.logger.warning(f"[SHUTDOWN] Error closing event socket server: {e}")
        
        # ソケットファイルを削除
        if self.event_socket_path.exists():
            try:
                self.event_socket_path.unlink()
                self.logger.info(f"[SHUTDOWN] Removed socket file: {self.event_socket_path}")
            except Exception as e:
                self.logger.warning(f"[SHUTDOWN] Error removing socket file: {e}")
        
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
        self.session_handler._handle_transfer(call_id)

    def _init_esl_connection(self) -> None:
        """
        FreeSWITCH Event Socket Interface (ESL) に接続
        
        :return: None
        """
        try:
            from libs.esl.ESL import ESLconnection
            
            esl_host = os.getenv("LC_FREESWITCH_ESL_HOST", "127.0.0.1")
            esl_port = os.getenv("LC_FREESWITCH_ESL_PORT", "8021")
            esl_password = os.getenv("LC_FREESWITCH_ESL_PASSWORD", "ClueCon")
            
            self.logger.info(f"[ESL] Connecting to FreeSWITCH ESL: {esl_host}:{esl_port}")
            self.esl_connection = ESLconnection(esl_host, esl_port, esl_password)
            
            if not self.esl_connection.connected():
                self.logger.error("[ESL] Failed to connect to FreeSWITCH ESL")
                self.esl_connection = None
                return
            
            self.logger.info("[ESL] Connected to FreeSWITCH ESL successfully")
        except ImportError:
            self.logger.warning("[ESL] ESL module not available, playback interruption will be disabled")
            self.esl_connection = None
        except Exception as e:
            self.logger.exception(f"[ESL] Failed to initialize ESL connection: {e}")
            self.esl_connection = None
    
    def _recover_esl_connection(self, max_retries: int = 3) -> bool:
        """
        FreeSWITCH ESL接続を自動リカバリ（接続が切れた場合に再接続を試みる、最大3回リトライ）
        
        :param max_retries: 最大リトライ回数（デフォルト: 3）
        :return: 再接続に成功したかどうか
        """
        return self.utils._recover_esl_connection(max_retries=max_retries)
    
    def _start_esl_event_listener(self) -> None:
        """
        FreeSWITCH ESLイベントリスナーを開始（CHANNEL_EXECUTE_COMPLETE監視）
        
        :return: None
        """
        self.utils._start_esl_event_listener()
    
    def _update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
        return self.utils._update_uuid_mapping_directly(call_id)
    
    def _handle_playback(self, call_id: str, audio_file: str) -> None:
        self.playback_manager._handle_playback(call_id, audio_file)

    async def _handle_playback_start(self, call_id: str, audio_file: str) -> None:
        await self.playback_manager._handle_playback_start(call_id, audio_file)

    async def _handle_playback_stop(self, call_id: str) -> None:
        await self.playback_manager._handle_playback_stop(call_id)
    
    def _handle_hangup(self, call_id: str) -> None:
        self.session_handler._handle_hangup(call_id)

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
        return self.utils._get_effective_call_id(addr)
    
    def _maybe_send_audio_level(self, rms: int) -> None:
        """RMS値を正規化して、一定間隔で音量レベルを管理画面に送信。"""
        self.utils._maybe_send_audio_level(rms)

    def _complete_console_call(self) -> None:
        if not self.console_bridge.enabled or not self.call_id or self.call_completed:
            return
        call_id_to_complete = self.call_id
        try:
            self.console_bridge.complete_call(call_id_to_complete, ended_at=datetime.utcnow())
            # ストリーミングモード: call_idの状態をリセット
            if self.streaming_enabled:
                self.ai_core.reset_call(call_id_to_complete)
            # 明示的な通話終了処理（フラグクリア）
            if hasattr(self.ai_core, 'on_call_end'):
                self.ai_core.on_call_end(call_id_to_complete, source="_complete_console_call")
            # 【追加】通話ごとのASRインスタンスをクリーンアップ
            if hasattr(self.ai_core, 'cleanup_asr_instance'):
                self.ai_core.cleanup_asr_instance(call_id_to_complete)
            self.call_completed = True
            self.call_id = None
            self.recent_dialogue.clear()
            self.transfer_notified = False
            # 音量レベル送信もリセット
            self.last_audio_level_sent = 0.0
            self.last_audio_level_time = 0.0
            # 補正用の変数もリセット
        except Exception as e:
            self.logger.error(f"[COMPLETE_CALL_ERR] Error during _complete_console_call for call_id={call_id_to_complete}: {e}", exc_info=True)
        finally:
            # ★どんなエラーがあっても、ここは必ず実行する★
            self.logger.warning(f"[FINALLY_BLOCK_ENTRY] Entered finally block for call_id={call_id_to_complete}")
            if call_id_to_complete:
                complete_time = time.time()
                # _active_calls から削除
                self.logger.warning(f"[FINALLY_ACTIVE_CALLS] Before removal: call_id={call_id_to_complete} in _active_calls={call_id_to_complete in self._active_calls if hasattr(self, '_active_calls') else False}")
                if hasattr(self, '_active_calls') and call_id_to_complete in self._active_calls:
                    self._active_calls.remove(call_id_to_complete)
                    self.logger.warning(f"[COMPLETE_CALL_DONE] Removed {call_id_to_complete} from active_calls (finally block) at {complete_time:.3f}")
                self.logger.warning(f"[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id={call_id_to_complete} in _active_calls={call_id_to_complete in self._active_calls if hasattr(self, '_active_calls') else False}")
                
                # 管理用データのクリーンアップ
                if call_id_to_complete in self._recovery_counts:
                    del self._recovery_counts[call_id_to_complete]
                if call_id_to_complete in self._initial_sequence_played:
                    self._initial_sequence_played.discard(call_id_to_complete)
                if call_id_to_complete in self._last_processed_sequence:
                    del self._last_processed_sequence[call_id_to_complete]
                self._last_voice_time.pop(call_id_to_complete, None)
                self._last_silence_time.pop(call_id_to_complete, None)
                self._last_tts_end_time.pop(call_id_to_complete, None)
                self._last_user_input_time.pop(call_id_to_complete, None)
                self._silence_warning_sent.pop(call_id_to_complete, None)
                if hasattr(self, '_initial_tts_sent'):
                    self._initial_tts_sent.discard(call_id_to_complete)
                self.logger.debug(f"[CALL_CLEANUP] Cleared state for call_id={call_id_to_complete}")
        self.user_turn_index = 0
        self.call_start_time = None
        self._reset_call_state()

    def _load_wav_as_ulaw8k(self, wav_path: Path) -> bytes:
        return self.playback_manager._load_wav_as_ulaw8k(wav_path)

    async def _queue_initial_audio_sequence(self, client_id: Optional[str]) -> None:
        await self.playback_manager._queue_initial_audio_sequence(client_id)

    def _generate_silence_ulaw(self, duration_sec: float) -> bytes:
        return self.playback_manager._generate_silence_ulaw(duration_sec)
    
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
        self.initial_sequence_completed = False
        self.initial_sequence_completed_time = None
        if self._asr_enable_timer:
            try:
                self._asr_enable_timer.cancel()
            except Exception:
                pass
            self._asr_enable_timer = None
        if was_playing:
            self.logger.info("[INITIAL_SEQUENCE] OFF: call state reset (initial_sequence_playing=False)")
        self.tts_queue.clear()
        self.is_speaking_tts = False
        self.audio_buffer = bytearray()
        self.current_segment_start = None
        self.is_user_speaking = False
        self.last_voice_time = time.time()
        self.rtp_peer = None
        self._rtp_src_addr = None  # 受信元アドレスもリセット
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
        await self.asr_manager.handle_asr_result(
            text, audio_duration, inference_time, end_to_text_delay
        )

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
        await self.monitor_manager._no_input_monitor_loop()
    
    async def _play_tts(self, call_id: str, text: str):
        """TTS音声を再生する"""
        self.logger.info(f"[PLAY_TTS] dispatching text='{text}' to TTS queue for {call_id}")
        try:
            self._send_tts(call_id, text, None, False)
        except Exception as e:
            self.logger.error(f"TTS playback failed for call_id={call_id}: {e}", exc_info=True)
    
    async def _play_silence_warning(self, call_id: str, warning_interval: float):
        """
        無音時に流すアナウンス（音源ファイルから再生）
        
        :param call_id: 通話ID
        :param warning_interval: 警告間隔（5.0, 15.0, 25.0）
        """
        try:
            # クライアントIDを取得（未設定の場合はデフォルト値を使用）
            effective_client_id = self.client_id or self.default_client_id or "000"
            
            # 警告間隔に応じて音源ファイル名を決定
            audio_file_map = {
                5.0: "000-004.wav",
                15.0: "000-005.wav",
                25.0: "000-006.wav"
            }
            audio_filename = audio_file_map.get(warning_interval)
            
            if not audio_filename:
                self.logger.warning(f"[SILENCE_WARNING] Unknown warning_interval={warning_interval}, skipping")
                return
            
            # クライアントごとの音声ディレクトリパスを構築
            audio_dir = Path(_PROJECT_ROOT) / "clients" / effective_client_id / "audio"
            audio_path = audio_dir / audio_filename
            
            # ファイル存在確認
            if not audio_path.exists():
                self.logger.warning(
                    f"[SILENCE_WARNING] Audio file not found: {audio_path} "
                    f"(client_id={effective_client_id}, interval={warning_interval:.0f}s)"
                )
                return
            
            self.logger.info(
                f"[SILENCE_WARNING] call_id={call_id} interval={warning_interval:.0f}s "
                f"audio_file={audio_path} client_id={effective_client_id}"
            )
            
            # 音源ファイルを読み込んでキューに追加
            try:
                ulaw_payload = self._load_wav_as_ulaw8k(audio_path)
                chunk_size = 160  # 20ms @ 8kHz
                
                # TTSキューに追加
                for i in range(0, len(ulaw_payload), chunk_size):
                    self.tts_queue.append(ulaw_payload[i : i + chunk_size])
                
                # TTS送信フラグを立てる
                self.is_speaking_tts = True
                self._tts_sender_wakeup.set()
                
                self.logger.debug(
                    f"[SILENCE_WARNING] Enqueued {len(ulaw_payload) // chunk_size} chunks "
                    f"from {audio_path}"
                )
            except Exception as e:
                self.logger.error(
                    f"[SILENCE_WARNING] Failed to load audio file {audio_path}: {e}",
                    exc_info=True
                )
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
        await self.session_handler._handle_no_input_timeout(call_id)

    async def _log_monitor_loop(self):
        """
        ログファイルを監視し、HANDOFF_FAIL_TTS_REQUESTメッセージを検出してTTSアナウンスを送信
        """
        await self.network_manager._log_monitor_loop()

    async def _event_socket_server_loop(self) -> None:
        """
        FreeSWITCHイベント受信用Unixソケットサーバー
        
        gateway_event_listener.pyからイベントを受信して、
        on_call_start() / on_call_end() を呼び出す
        """
        await self.network_manager._event_socket_server_loop()
    
    def _generate_call_id_from_uuid(self, uuid: str, client_id: str) -> str:
        """
        UUIDからcall_idを生成
        
        :param uuid: FreeSWITCH UUID
        :param client_id: クライアントID
        :return: call_id
        """
        # console_bridgeのissue_call_id()を使用（標準的なcall_id生成）
        if hasattr(self, 'console_bridge') and self.console_bridge:
            call_id = self.console_bridge.issue_call_id(client_id)
            self.logger.info(f"[EVENT_SOCKET] Generated call_id={call_id} from uuid={uuid} client_id={client_id}")
        else:
            # フォールバック: タイムスタンプベースでcall_idを生成
            call_id = f"in-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.logger.warning(f"[EVENT_SOCKET] console_bridge not available, using fallback call_id={call_id}")
        
        return call_id

# ========================================
# Main Entry Point
# ========================================

if __name__ == '__main__':
    # 環境変数: Google 認証ファイルを明示的に指定（必要に応じて実際のパスに変更してください）
    import os
    # 既存の認証ファイル候補
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/opt/libertycall/config/google-credentials.json")

    # ログ設定
    import logging
    # ログディレクトリを作成
    log_dir = Path("/opt/libertycall/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/opt/libertycall/logs/realtime_gateway.log', encoding='utf-8')
        ]
    )
    
    print("[MAIN_DEBUG] main function started", flush=True)
    import argparse
    
    parser = argparse.ArgumentParser(description="Liberty Call Realtime Gateway")
    parser.add_argument(
        '--rtp_port',
        type=int,
        default=None,
        help='Override RTP listen port (default: from config or env LC_RTP_PORT)'
    )
    parser.add_argument(
        '--uuid',
        type=str,
        required=False,
        default=None,
        help='Unique identifier for this gateway instance (passed from event listener)'
    )
    args = parser.parse_args()
    
    # UUID引数のログ出力
    if args.uuid:
        print(f"[GATEWAY_INIT] Starting with UUID: {args.uuid}", flush=True)
    
    # Load configuration
    config_path = Path(_PROJECT_ROOT) / "config" / "gateway.yaml"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        # Fallback to default config
        config = {
            "rtp": {
                "listen_host": "0.0.0.0",
                "listen_port": 7002,
                "payload_type": 0,
                "sample_rate": 8000
            },
            "ws": {
                "url": "ws://localhost:8000/ws",
                "reconnect_delay_sec": 5
            }
        }
    
    # Create gateway instance
    gateway = RealtimeGateway(config, rtp_port_override=args.rtp_port)
    print(f"[MAIN_DEBUG] RealtimeGateway created, uuid={args.uuid}", flush=True)
    gateway.uuid = args.uuid  # ESL受信のためのUUID保持
    set_gateway_instance(gateway)

    def _run_asr_controller():
        logger = logging.getLogger(__name__)
        try:
            logger.info("[ASR_CONTROLLER] Starting FastAPI server on 127.0.0.1:8000")
            config = uvicorn.Config(
                asr_app,
                host="127.0.0.1",
                port=8000,
                log_level="info",
                access_log=True,
            )
            server = uvicorn.Server(config)
            server.run()
        except Exception:
            logger.exception("[ASR_CONTROLLER] FastAPI server terminated due to error")

    asr_thread = threading.Thread(
        target=_run_asr_controller, name="ASRControllerThread", daemon=True
    )
    asr_thread.start()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger = logging.getLogger(__name__)
        logger.info(f"[SIGNAL] Received signal {sig}, initiating shutdown...")
        asyncio.create_task(gateway.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the gateway
    try:
        asyncio.run(gateway.start())
    except KeyboardInterrupt:
        pass
    finally:
        logger = logging.getLogger(__name__)
        logger.info("[EXIT] Gateway stopped")

