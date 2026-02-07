"""Gateway lifecycle and ESL recovery helpers."""
from __future__ import annotations

import asyncio
import collections
import os
import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from ..core.gateway_utils import GatewayUtils


class GatewayLifecycleManager:
    def __init__(self, utils: "GatewayUtils") -> None:
        self.utils = utils
        self.gateway = utils.gateway
        self.logger = utils.logger

    def init_state(self, console_bridge, audio_manager) -> None:
        gateway = self.gateway
        gateway._debug_packet_count = 0
        gateway._last_processed_sequence = {}
        gateway._initial_sequence_played = set()

        gateway.rtp_peer = None
        gateway.websocket = None
        gateway.rtp_transport = None
        gateway.rtp_builder = None
        gateway.running = False
        gateway.shutdown_event = asyncio.Event()

        gateway.audio_buffer = bytearray()
        gateway.tts_queue = collections.deque(maxlen=100)
        gateway.is_speaking_tts = False
        gateway.last_voice_time = time.time()
        gateway.is_user_speaking = False

        gateway._pending_transfer_call_id = None
        gateway._transfer_task_queue = collections.deque()
        gateway.fs_rtp_monitor = gateway.monitor_manager.fs_rtp_monitor

        gateway.BARGE_IN_THRESHOLD = 1000
        gateway.SILENCE_DURATION = 0.9
        gateway.MAX_SEGMENT_SEC = 2.3
        gateway.MIN_AUDIO_LEN = 16000
        gateway.MIN_RMS_FOR_ASR = 80
        gateway.NO_INPUT_TIMEOUT = 10.0
        gateway.NO_INPUT_STREAK_LIMIT = 4
        gateway.MAX_NO_INPUT_TIME = 60.0
        gateway.SILENCE_WARNING_INTERVALS = [5.0, 15.0, 25.0]
        gateway.SILENCE_HANGUP_TIME = 60.0
        gateway.NO_INPUT_SILENT_PHRASES = {"すみません", "ええと", "あの"}

        gateway.current_segment_start = None
        gateway.turn_id = 1
        gateway.turn_rms_values = []
        gateway.user_turn_index = 0
        gateway.call_start_time = None
        gateway.max_call_duration_sec = float(
            os.getenv("LC_MAX_CALL_DURATION_SEC", "1800")
        )

        gateway.rtp_packet_count = 0
        gateway.last_rtp_packet_time = 0.0
        gateway.RTP_PEER_IDLE_TIMEOUT = float(
            os.getenv("LC_RTP_PEER_IDLE_TIMEOUT", "2.0")
        )

        gateway.client_id = None
        gateway.client_profile = None
        gateway.rules = None
        gateway.console_bridge = console_bridge
        gateway.audio_manager = audio_manager
        gateway.default_client_id = os.getenv("LC_DEFAULT_CLIENT_ID", "000")
        gateway.console_api_url = os.getenv(
            "LIBERTYCALL_CONSOLE_API_BASE_URL",
            "http://localhost:8001",
        )

        gateway.initial_sequence_played = False
        gateway.initial_sequence_playing = False
        gateway.initial_sequence_completed = False
        gateway.initial_sequence_completed_time = None
        gateway._asr_enable_timer = None
        gateway.initial_silence_sec = 0.5
        gateway.call_id = None
        gateway.current_state = "init"

        gateway.last_audio_level_sent = 0.0
        gateway.last_audio_level_time = 0.0
        gateway.AUDIO_LEVEL_INTERVAL = 0.2
        gateway.AUDIO_LEVEL_THRESHOLD = 0.05
        gateway.RMS_MAX = 32767.0
        gateway.recent_dialogue = collections.deque(maxlen=8)
        gateway.transfer_notified = False
        gateway.call_completed = False

        gateway._stream_chunk_counter = 0
        gateway._last_feed_time = time.time()

        gateway._last_user_input_time = {}
        gateway._last_tts_end_time = {}
        gateway._no_input_timers = {}
        gateway._no_input_elapsed = {}
        gateway._silence_warning_sent = {}
        gateway._last_silence_time = {}
        gateway._last_voice_time = {}
        gateway._active_calls = set()
        gateway._initial_tts_sent = set()
        gateway._last_tts_text = None
        gateway._call_addr_map = {}
        gateway._recovery_counts = {}

        gateway.recording_enabled = os.getenv("LC_ENABLE_RECORDING", "0") == "1"
        gateway.recording_file = None
        gateway.recording_path = None
        if gateway.recording_enabled:
            recordings_dir = Path("/opt/libertycall/recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(
                "録音機能が有効です。録音ファイルは %s に保存されます。",
                recordings_dir,
            )

        gateway.event_socket_path = Path("/tmp/liberty_gateway_events.sock")
        gateway.event_server = None

    async def start(self) -> None:
        import os
        from .gateway_component_factory import GatewayComponentFactory
        
        os.write(2, b"[TRACE_LIFECYCLE_ENTRY] async def start() called\n")
        gateway = self.gateway
        os.write(2, b"[TRACE_START_1] Starting lifecycle manager\n")
        self.logger.info("[TRACE_LIFECYCLE] 1: Starting lifecycle manager")
        self.logger.info("[RTP_START] RealtimeGateway.start() called")
        gateway.running = True
        gateway.rtp_builder = self.utils.rtp_builder_cls(
            gateway.payload_type, gateway.sample_rate
        )

        try:
            loop = asyncio.get_running_loop()
            os.write(2, b"[TRACE_START_2] Creating RTP socket\n")

            # ソケットをメンバに保持してbind（IPv4固定、0.0.0.0で全インターフェースにバインド）
            gateway.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            gateway.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            gateway.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError as e:
            os.write(2, f"[TRACE_START_ERROR] Socket error: {e}\n".encode())
            # 【bind error対策】ポートが競合したら即座にポートをズラしてでも無理やり口を開けろ
            if "Address already in use" in str(e):
                original_port = gateway.rtp_port
                for offset in range(1, 100):  # 100ポートまで試す
                    test_port = original_port + offset
                    try:
                        gateway.rtp_sock.bind(("0.0.0.0", test_port))
                        gateway.rtp_sock.setblocking(False)
                        bound_addr = gateway.rtp_sock.getsockname()
                        gateway.rtp_port = test_port  # ポートを更新
                        self.logger.warning(f"[RTP_BIND_RETRY] Bind error on {original_port}, successfully bound to {test_port}")
                        self.logger.warning(f"[RTP_RECEIVER_START] Listening on {bound_addr[0]}:{bound_addr[1]} for RTP packets (recovered)")
                        break
                    except OSError:
                        continue
                else:
                    raise e  # 100ポート試してもダメなら諦める
            else:
                raise e
        else:
            gateway.rtp_sock.setblocking(False)  # asyncio用にノンブロッキングへ
            gateway.rtp_sock.bind(("0.0.0.0", gateway.rtp_port))  # バインドを追加
            bound_addr = gateway.rtp_sock.getsockname()
            self.logger.info("[RTP_BIND_FINAL] Bound UDP socket to %s", bound_addr)
            # 【強制生存確認】RTP受信スレッドがどのIP:Portでリッスンを開始したかをログに吐く
            self.logger.warning(f"[RTP_RECEIVER_START] Listening on {bound_addr[0]}:{bound_addr[1]} for RTP packets")

            # asyncioにソケットを渡す
            os.write(2, b"[TRACE_START_3] Creating datagram endpoint\n")
            self.logger.info("[DEBUG_ENDPOINT] About to create datagram endpoint")
            gateway.rtp_transport, _ = await loop.create_datagram_endpoint(
                lambda: self.utils.rtp_protocol_cls(gateway),
                sock=gateway.rtp_sock,
            )
            os.write(2, b"[TRACE_START_4] Datagram endpoint created\n")
            self.logger.info(f"[DEBUG_ENDPOINT] Datagram endpoint created successfully: {gateway.rtp_transport}")
            self.logger.info(
                "[RTP_READY_FINAL] RTP listener active and awaiting packets on %s",
                bound_addr,
            )

            # ComponentFactoryを使用して各コンポーネントをセットアップ
            factory = GatewayComponentFactory(self.utils)
            factory.setup_all_components()
            
            os.write(2, b"[TRACE_START_6] Initialization complete\n")

            # サービスを維持（停止イベントを待つ）
            await gateway.shutdown_event.wait()

    def shutdown(self, remove_handler_fn=None) -> None:
        """シャットダウンをLoopManagerに委譲"""
        from .gateway_loop_manager import GatewayLoopManager
        loop_manager = GatewayLoopManager(self)
        return asyncio.run(loop_manager.shutdown(remove_handler_fn))
