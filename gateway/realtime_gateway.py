#!/usr/bin/env python3
"""RealtimeGateway entrypoint (set LC_GATEWAY_PORT for dev runs)."""
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
import audioop
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
from libertycall.gateway.monitor_manager import GatewayMonitorManager, ESLAudioReceiver
from libertycall.gateway.audio_processor import GatewayAudioProcessor
from libertycall.gateway.gateway_utils import GatewayUtils, IGNORE_RTP_IPS
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
        
        # FreeSWITCH/localhostからのループバックは除外
        if addr[0] in IGNORE_RTP_IPS:
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

class RealtimeGateway:
    def __init__(self, config: dict, rtp_port_override: Optional[int] = None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        # 起動確認用ログ（修正版が起動したことを示す）
        self.logger.warning("[DEBUG_VERSION] RealtimeGateway initialized with UPDATED LOGGING logic.")
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
        self.audio_manager = AudioManager(_PROJECT_ROOT)
        self.utils.init_state(console_bridge, self.audio_manager)
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
        await self.playback_manager._tts_sender_loop()

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
        await self.network_manager._ws_client_loop()

    def _free_port(self, port: int):
        """安全にポートを解放する（自分自身は殺さない）"""
        self.utils._free_port(port)

    async def _ws_server_loop(self):
        await self.network_manager._ws_server_loop()

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
        await self.utils.shutdown(remove_handler)

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
        self.utils.complete_console_call()

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
        self.utils.reset_call_state()

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

