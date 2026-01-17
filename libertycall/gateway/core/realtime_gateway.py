#!/usr/bin/env python3
"""RealtimeGateway entrypoint (set LC_GATEWAY_PORT for dev runs)."""
import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import Optional, Tuple, Dict
import time
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
from libertycall.console_bridge import console_bridge

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
logger_debug = logging.getLogger("libertycall.gateway.core.ai_core")
logger_debug.warning("DEBUG_IMPORT_CHECK: AICore class from %r", AICore.__module__)
logger_debug.warning("DEBUG_IMPORT_CHECK_FILE: ai_core file = %r", AICore.__init__.__code__.co_filename)
try:
    from ..audio.audio_manager import AudioManager
except ImportError:  # 実行形式(py gateway/realtime_gateway.py)との両立
    from audio_manager import AudioManager  # type: ignore

def load_config(config_path: str | Path) -> dict:
    return GatewayConfigManager.load_config(Path(config_path))


class RealtimeGateway:
    def __init__(self, config: dict, rtp_port_override: Optional[int] = None):
        self.config = config
        self.logger = logging.getLogger(__name__)
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
        # TTS 送信用コールバックを設定
        self.ai_core.tts_callback = self._send_tts
        self.ai_core.transfer_callback = self._handle_transfer
        # 自動切断用コールバックを設定
        self.ai_core.hangup_callback = self._handle_hangup
        # 音声再生用コールバックを設定
        self.ai_core.playback_callback = self._handle_playback
        
        # FreeSWITCH ESL接続を初期化（再生制御・割り込み用）
        self.esl_connection = None
        self.esl_manager._init_esl_connection()
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

    def __getattr__(self, name: str):
        alias_map = {
            "_ensure_console_session": self.console_manager.ensure_console_session,
            "_append_console_log": self.console_manager.append_console_log,
            "_record_dialogue": self.console_manager.record_dialogue,
            "_build_handover_summary": self.console_manager.build_handover_summary,
            "_generate_call_id_from_uuid": self.console_manager.generate_call_id_from_uuid,
            "_init_esl_connection": self.esl_manager._init_esl_connection,
        }
        if name in alias_map:
            return alias_map[name]

        delegates = (
            self.playback_manager,
            self.network_manager,
            self.utils,
            self.activity_monitor,
            self.console_manager,
            self.esl_manager,
            self.session_handler,
            self.audio_processor,
            self.monitor_manager,
            self.asr_manager,
        )
        for delegate in delegates:
            attr = getattr(type(delegate), name, None)
            if attr is not None:
                return getattr(delegate, name)
            if name in getattr(delegate, "__dict__", {}):
                return delegate.__dict__[name]
        raise AttributeError(f"{type(self).__name__} has no attribute {name}")

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

    async def handle_rtp_packet(self, data: bytes, addr: Tuple[str, int]):
        await self.asr_manager.process_rtp_audio(data, addr)

    async def shutdown(self):
        """Graceful shutdown for RTP transport and all resources"""
        await self.utils.shutdown(remove_handler)

    def _request_transfer(self, call_id: str) -> None:
        state_label = f"AI_HANDOFF:{call_id or 'UNKNOWN'}"
        self.logger.debug("RealtimeGateway: transfer callback invoked (%s)", state_label)
        self._handle_transfer(call_id)


if __name__ == "__main__":
    try:
        from .gateway_main import main
    except ImportError:
        from gateway_main import main

    raise SystemExit(main())


