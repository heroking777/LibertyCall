#!/usr/bin/env python3
"""RealtimeGateway entrypoint (set LC_GATEWAY_PORT for dev runs)."""
import asyncio
import logging
import sys
import os
import time

from pathlib import Path
from typing import Optional, Tuple, Dict
import audioop
# 【緊急修正】インポートパスを強制的に通す
sys.path.append('/opt/libertycall')

# サバイバル・インポート
try:
    import audioop
    AUDIOOP_AVAILABLE = True
    logging.info("audioop module imported successfully")
except ImportError as e:
    AUDIOOP_AVAILABLE = False
    logging.error(f"audioop import failed: {e}")
    logging.warning("Attempting to install audioop-lts...")
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "audioop-lts"], check=True)
        import audioop
        AUDIOOP_AVAILABLE = True
        logging.info("audioop-lts installed and imported successfully")
    except Exception as install_e:
        logging.error(f"Failed to install audioop-lts: {install_e}")
        AUDIOOP_AVAILABLE = False
try:
    from scapy.all import sniff, IP, UDP
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
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
from ..core.ai_core import AICore
from ..asr.asr_manager import GatewayASRManager
from ..audio.playback_manager import GatewayPlaybackManager
from ..core.call_session_handler import GatewayCallSessionHandler
from ..common.network_manager import GatewayNetworkManager
from ..core.monitor_manager import GatewayMonitorManager, ESLAudioReceiver
from ..audio.audio_processor import GatewayAudioProcessor
from ..core.gateway_utils import GatewayUtils
from ..core.gateway_event_router import GatewayEventRouter
from ..core.gateway_config_manager import GatewayConfigManager
from ..core.gateway_activity_monitor import GatewayActivityMonitor
from ..core.gateway_console_manager import GatewayConsoleManager
from ..core.gateway_esl_manager import GatewayESLManager
from ..asr.gateway_rtp_protocol import RTPPacketBuilder, RTPProtocol
from console_bridge import console_bridge

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
logger_debug = logging.getLogger("gateway.core.ai_core")
logger_debug.warning("DEBUG_IMPORT_CHECK: AICore class from %r", AICore.__module__)
logger_debug.warning("DEBUG_IMPORT_CHECK_FILE: ai_core file = %r", AICore.__init__.__code__.co_filename)
from ..audio import AudioManager
def load_config(config_path: str | Path) -> dict:
    return GatewayConfigManager.load_config(Path(config_path))


class RealtimeGateway:
    def __init__(self, config: dict, rtp_port_override: Optional[int] = None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # ASRプロバイダのデフォルト設定
        if 'LC_ASR_PROVIDER' not in os.environ:
            os.environ['LC_ASR_PROVIDER'] = 'google'
        
        # 起動確認用ログ（修正版が起動したことを示す）
        self.logger.warning("[DEBUG_VERSION] RealtimeGateway initialized with UPDATED LOGGING logic.")
        self.config_manager = GatewayConfigManager(self.logger)
        self.rtp_host = config["rtp"]["listen_host"]
        # ポート番号の優先順位: コマンドライン引数 > LC_RTP_PORT > LC_GATEWAY_PORT > gateway.yaml > 固定値 7100
        self.rtp_port = self.config_manager.resolve_rtp_port(
            config, rtp_port_override=rtp_port_override
        )
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
        self.router = GatewayEventRouter(self)
        self.console_manager = GatewayConsoleManager(self)
        self.activity_monitor = GatewayActivityMonitor(self)
        self.esl_manager = GatewayESLManager(self)
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
        
        # FreeSWITCH ESL接続を初期化（再生制御・割り込み用）
        self.esl_connection = None
        self.esl_manager._init_esl_connection()
        
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

        # ASRマネージャ初期化前にstream_handlerとbatch_handlerを設定
        # ダミーハンドラーを設定して初期化エラーを回避
        self.stream_handler = None
        self.batch_handler = None
        
        self.asr_manager = GatewayASRManager(self)
        self._unmapped_ssrcs: Dict[int, float] = {}
        # Playback/TTSマネージャ初期化
        self.playback_manager = GatewayPlaybackManager(self)
        # TTS/Playback callbacks now available
        self.ai_core.tts_callback = self.playback_manager._send_tts
        self.ai_core.transfer_callback = self._handle_transfer
        self.ai_core.hangup_callback = self._handle_hangup
        self.ai_core.playback_callback = self.playback_manager._handle_playback
        self.logger.info(
            "HANGUP_CALLBACK_SET: hangup_callback=%s",
            "set" if self.ai_core.hangup_callback else "none"
        )
        
        # Factory呼び出し
        from .gateway_component_factory import GatewayComponentFactory
        self.factory = GatewayComponentFactory(self)
        self.factory.setup_all_components()

    async def start(self):
        await self.utils.start()

    def __getattr__(self, name: str):
        alias_map = {
            "_ensure_console_session": "console_manager",
            "_append_console_log": "console_manager",
            "_record_dialogue": "console_manager",
            "_build_handover_summary": "console_manager",
            "_generate_call_id_from_uuid": "console_manager",
            "_init_esl_connection": "esl_manager",
        }
        if name in alias_map:
            manager = object.__getattribute__(self, alias_map[name])
            return getattr(manager, name)

        delegate_names = (
            "playback_manager",
            "network_manager",
            "utils",
            "activity_monitor",
            "console_manager",
            "esl_manager",
            "session_handler",
            "audio_processor",
            "monitor_manager",
            "asr_manager",
        )
        for delegate_name in delegate_names:
            try:
                delegate = object.__getattribute__(self, delegate_name)
            except AttributeError:
                continue
            if delegate is None:
                continue
            attr = getattr(type(delegate), name, None)
            if attr is not None:
                return getattr(delegate, name)
            if name in getattr(delegate, "__dict__", {}):
                return delegate.__dict__[name]
        raise AttributeError(f"{type(self).__name__} has no attribute {name}")

    def _stop_recording(self) -> None:
        self.activity_monitor._stop_recording()

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
                    self.logger.debug(
                        "STREAMING_LOOP: polled call_id=%s result=FOUND (poll_count=%s)",
                        effective_call_id,
                        poll_count,
                    )
                    text, audio_duration, inference_time, end_to_text_delay = result
                    await self.asr_manager.handle_asr_result(
                        text, audio_duration, inference_time, end_to_text_delay
                    )
                # ポーリングの詳細ログはDEBUG（スパム防止）
            except Exception as e:
                self.logger.error(f"Streaming poll error: {e}", exc_info=True)
            await asyncio.sleep(0.1)  # 100ms間隔でポーリング

    async def handle_rtp_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
        """
        RTPパケット受信処理
        SSRCを抽出してcall_idを解決し、ASRManagerに転送
        """
        try:
            # パケット長チェック（RTP最小ヘッダー12バイト）
            if len(data) < 12:
                return
            
            # RTPバージョン確認（最初のバイトの上位2ビット）
            version = (data[0] >> 6) & 0x03
            if version != 2:
                return
            
            # SSRC抽出（8-11バイト目、ビッグエンディアン）
            ssrc = int.from_bytes(data[8:12], byteorder='big')
            
            # call_id解決（ASRManager経由）
            call_id = None
            if self.asr_manager:
                call_id = self.asr_manager.resolve_call_id(ssrc=ssrc, addr=addr)
            
            # call_idが見つからない場合の処理
            if not call_id:
                # 未登録SSRCの記録（メモリリーク防止付き）
                if not hasattr(self, '_unmapped_ssrcs'):
                    self._unmapped_ssrcs = {}
                
                # 初回のみログ出力
                if ssrc not in self._unmapped_ssrcs:
                    self.logger.debug(
                        f"\U0001f4e6 Unmapped RTP: ssrc={ssrc:#010x}, addr={addr}. "
                        f"Waiting for CHANNEL_ANSWER..."
                    )
                    self._unmapped_ssrcs[ssrc] = time.time()
                
                # 60秒以上前のエントリを削除
                import time as _time
                now = _time.time()
                self._unmapped_ssrcs = {
                    k: v for k, v in self._unmapped_ssrcs.items()
                    if now - v < 60
                }
                
                return
            
            # RTPペイロード抽出
            payload = self._extract_rtp_payload(data)
            if not payload:
                self.logger.debug(f"Empty RTP payload for call {call_id}")
                return
            
            # ASRManagerに転送
            await self.asr_manager.process_rtp_audio_for_call(call_id, payload)
            
        except Exception as e:
            self.logger.error(f"\u274c Error in handle_rtp_packet from {addr}: {e}", exc_info=True)

    def _extract_rtp_payload(self, rtp_packet: bytes) -> bytes:
        """
        RTPパケットからペイロードを抽出
        
        RTPヘッダー構造:
        - Byte 0: V(2bit)|P(1bit)|X(1bit)|CC(4bit)
        - Byte 1: M(1bit)|PT(7bit)
        - Byte 2-3: Sequence Number
        - Byte 4-7: Timestamp
        - Byte 8-11: SSRC
        - Byte 12-: CSRC list (CC個 * 4byte)
        - 拡張ヘッダー（Xが1の場合）
        - ペイロード
        - パディング（Pが1の場合）
        """
        try:
            if len(rtp_packet) < 12:
                return b''
            
            # ビットフラグ抽出
            padding = (rtp_packet[0] >> 5) & 0x01
            extension = (rtp_packet[0] >> 4) & 0x01
            csrc_count = rtp_packet[0] & 0x0F
            
            # ヘッダー長計算（基本12バイト + CSRC）
            header_length = 12 + (csrc_count * 4)
            
            # 拡張ヘッダー処理
            if extension:
                if len(rtp_packet) < header_length + 4:
                    self.logger.warning("RTP packet too short for extension header")
                    return b''
                
                # 拡張ヘッダー長（16bitワード単位、オフセット+2から2バイト）
                ext_length_words = int.from_bytes(
                    rtp_packet[header_length + 2:header_length + 4],
                    byteorder='big'
                )
                # 拡張ヘッダー全体 = 4バイト固定部 + 可変長部
                header_length += 4 + (ext_length_words * 4)
            
            # ヘッダー長チェック
            if len(rtp_packet) <= header_length:
                self.logger.warning(
                    f"RTP header ({header_length}B) >= packet ({len(rtp_packet)}B)"
                )
                return b''
            
            # ペイロード抽出
            payload = rtp_packet[header_length:]
            
            # パディング除去
            if padding and len(payload) > 0:
                padding_length = payload[-1]
                # パディング長の妥当性チェック
                if 0 < padding_length < len(payload):
                    payload = payload[:-padding_length]
                else:
                    self.logger.warning(f"Invalid padding length: {padding_length}")
            
            return payload
            
        except Exception as e:
            self.logger.error(f"\u274c Error extracting RTP payload: {e}", exc_info=True)
            return b''

    async def shutdown(self):
        """Graceful shutdown for RTP transport and all resources"""
        await self.utils.shutdown(remove_handler)

    def _request_transfer(self, call_id: str) -> None:
        state_label = f"AI_HANDOFF:{call_id or 'UNKNOWN'}"
        self.logger.debug("RealtimeGateway: transfer callback invoked (%s)", state_label)
        self._handle_transfer(call_id)

    def _queue_initial_audio_sequence(self, client_id: Optional[str]) -> None:
        """Compatibility wrapper so sync callers can trigger initial audio."""
        coro = self.playback_manager._queue_initial_audio_sequence(client_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            asyncio.create_task(coro)
            return

        asyncio.run(coro)

    def _log_unmapped_ssrc(self, ssrc: int, addr: Tuple[str, int]) -> None:
        now = time.time()
        last_logged = self._unmapped_ssrcs.get(ssrc)
        if last_logged is None or (now - last_logged) > 10:
            self.logger.debug(
                "[RTP_HANDLER] Unmapped SSRC=0x%08x addr=%s; awaiting CHANNEL_ANSWER",
                ssrc,
                addr,
            )
            self._unmapped_ssrcs[ssrc] = now

        # クリーンアップ（60秒以上経過したエントリを除去）
        stale_threshold = now - 60
        self._unmapped_ssrcs = {
            key: ts for key, ts in self._unmapped_ssrcs.items() if ts >= stale_threshold
        }

    def _extract_rtp_payload(self, packet: bytes) -> bytes:
        try:
            if len(packet) < 12:
                return b""

            padding = (packet[0] >> 5) & 0x01
            extension = (packet[0] >> 4) & 0x01
            csrc_count = packet[0] & 0x0F

            header_length = 12 + (csrc_count * 4)

            if extension:
                if len(packet) < header_length + 4:
                    self.logger.warning("[RTP_HANDLER] Packet too short for extension header")
                    return b""
                ext_length_words = int.from_bytes(
                    packet[header_length + 2: header_length + 4], byteorder="big"
                )
                header_length += 4 + (ext_length_words * 4)

            if len(packet) <= header_length:
                self.logger.warning(
                    "[RTP_HANDLER] Header length %s exceeds packet size %s",
                    header_length,
                    len(packet),
                )
                return b""

            payload = packet[header_length:]

            if padding and payload:
                padding_length = payload[-1]
                if 0 < padding_length < len(payload):
                    payload = payload[:-padding_length]
                else:
                    self.logger.warning("[RTP_HANDLER] Invalid padding length=%s", padding_length)

            return payload
        except Exception as exc:
            self.logger.error("[RTP_HANDLER] Payload extraction failed: %s", exc, exc_info=True)
            return b""


if __name__ == "__main__":
    try:
        from .gateway_main import main
    except ImportError:
        from gateway_main import main

    raise SystemExit(main())


