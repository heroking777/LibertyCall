#!/usr/bin/env python3
"""RealtimeGateway entrypoint (set LC_GATEWAY_PORT for dev runs)."""
import asyncio
import logging
import signal
import sys
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict
import time
import uvicorn
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
from libertycall.gateway.ai_core import AICore
from libertycall.gateway.asr_manager import GatewayASRManager
from libertycall.gateway.playback_manager import GatewayPlaybackManager
from libertycall.gateway.call_session_handler import GatewayCallSessionHandler
from libertycall.gateway.network_manager import GatewayNetworkManager
from libertycall.gateway.monitor_manager import GatewayMonitorManager, ESLAudioReceiver
from libertycall.gateway.audio_processor import GatewayAudioProcessor
from libertycall.gateway.gateway_utils import GatewayUtils
from libertycall.gateway.gateway_event_router import GatewayEventRouter
from libertycall.gateway.gateway_config_manager import GatewayConfigManager
from libertycall.gateway.gateway_activity_monitor import GatewayActivityMonitor
from libertycall.gateway.gateway_rtp_protocol import RTPPacketBuilder, RTPProtocol
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
        self.activity_monitor = GatewayActivityMonitor(self)
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
        self.activity_monitor._start_recording()

    def _stop_recording(self) -> None:
        self.activity_monitor._stop_recording()

    def _reset_call_state(self) -> None:
        self.utils.reset_call_state()

    async def _process_streaming_transcript(
        self, text: str, audio_duration: float, inference_time: float, end_to_text_delay: float
    ):
        await self.asr_manager.handle_asr_result(
            text, audio_duration, inference_time, end_to_text_delay
        )

    async def _start_no_input_timer(self, call_id: str) -> None:
        await self.activity_monitor._start_no_input_timer(call_id)

    async def _no_input_monitor_loop(self):
        """無音状態を監視し、自動ハングアップを行う"""
        await self.monitor_manager._no_input_monitor_loop()
    
    async def _play_tts(self, call_id: str, text: str):
        """TTS音声を再生する"""
        self.logger.info(
            "[PLAY_TTS] dispatching text='%s' to TTS queue for %s",
            text,
            call_id,
        )
        try:
            self._send_tts(call_id, text, None, False)
        except Exception as e:
            self.logger.error(
                "TTS playback failed for call_id=%s: %s", call_id, e, exc_info=True
            )

    async def _play_silence_warning(self, call_id: str, warning_interval: float):
        await self.playback_manager._play_silence_warning(call_id, warning_interval)

    async def _wait_for_no_input_reset(self, call_id: str):
        await self.activity_monitor._wait_for_no_input_reset(call_id)
    
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
    GatewayConfigManager.setup_environment()

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
    config = GatewayConfigManager.load_config(config_path)
    
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

