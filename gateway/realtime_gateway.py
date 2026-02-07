#!/usr/bin/env python3
"""Realtime Gateway for RTP and ASR processing"""
import sys
sys.stderr.write("[CRITICAL_BOOT] Script process started\n")
sys.stderr.flush()

import traceback


def _rg_excepthook(exctype, value, tb):
    try:
        sys.stderr.write("[RG_TOPLEVEL_EXC]\n")
        traceback.print_exception(exctype, value, tb)
        sys.stderr.flush()
    except Exception:
        pass


sys.excepthook = _rg_excepthook

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Dict
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

# RTP受信トレース（本命プロセス用）
_GW_RTP_TRACE = "/tmp/gw3412042_rtp_trace.log"
_GW_TRACE_CNT = 0

def _gw_trace(msg: str) -> None:
    try:
        with open(_GW_RTP_TRACE, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} pid={os.getpid()} {msg}\n")
    except Exception:
        return

_gw_trace("[module_loaded] gateway.realtime_gateway imported")
sys.stderr.write(
    f"[RG_IMPORT] ts={time.time()} file={__file__} pid={os.getpid()} cwd={os.getcwd()}\n"
)
sys.stderr.flush()
sys.stderr.write(
    f"[RG_TOP] ts={time.time()} name={__name__} file={__file__} pid={os.getpid()} argv={sys.argv}\n"
)
sys.stderr.flush()

import os as _os, sys as _sys, time as _time
_RG_BUILD = "RG_BUILD_20260128_1855_A"
_os.write(
    2,
    f"{_time.time():.3f} [RG_BOOTLINE] build={_RG_BUILD} pid={_os.getpid()} file={__file__} argv={_sys.argv} cwd={_os.getcwd()}\n".encode(),
)
try:
    import gateway.core.gateway_component_factory as _gcf
    _os.write(2, f"{_time.time():.3f} [RG_WHICH] gcf_file={_gcf.__file__}\n".encode())
except Exception as _rg_gcf_exc:
    _os.write(2, f"{_time.time():.3f} [RG_WHICH] gcf_import_fail {_rg_gcf_exc!r}\n".encode())

_boot_logger = logging.getLogger("gateway.realtime_gateway.boot")


def _dump_import_paths() -> None:
    """ログで起動元パスを確定させる。"""
    try:
        import gateway.core.gateway_component_factory as gcf
        import gateway.common.network_manager as nm
        import gateway.common.network_socket_server as nss
    except Exception as exc:  # pragma: no cover - diagnostics only
        _boot_logger.error("[RG_BOOT] failed to import diagnostics modules: %s", exc, exc_info=True)
        return

    _boot_logger.info("[RG_BOOT] py=%s cwd=%s pid=%s", sys.executable, os.getcwd(), os.getpid())
    _boot_logger.info("[RG_BOOT] sys.path=%s", sys.path)
    _boot_logger.info("[RG_BOOT] gcf_file=%s", getattr(gcf, "__file__", None))
    _boot_logger.info("[RG_BOOT] nm_file=%s", getattr(nm, "__file__", None))
    _boot_logger.info("[RG_BOOT] nss_file=%s", getattr(nss, "__file__", None))

# --- プロジェクトルートを sys.path に追加 ---
_CURRENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CURRENT_DIR.parent         # /opt/libertycall
_REPO_PARENT = _PROJECT_ROOT.parent         # /opt
if str(_REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(_REPO_PARENT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 【インポートエラー対策】相対インポートを絶対インポートに修正
try:
    from gateway.core.ai_core import AICore
except ImportError:
    try:
        from core.ai_core import AICore
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import AICore from either gateway.core.ai_core or core.ai_core")
        sys.exit(1)

# --- モジュール読み込み ---
# 【インポートエラー対策】相対インポートを絶対インポートに修正
try:
    from gateway.core.ai_core import AICore
except ImportError:
    try:
        from core.ai_core import AICore
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import AICore from either gateway.core.ai_core or core.ai_core")
        sys.exit(1)

try:
    from gateway.asr.asr_manager import GatewayASRManager
except ImportError:
    try:
        from asr.asr_manager import GatewayASRManager
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayASRManager")
        sys.exit(1)

try:
    from gateway.audio.playback_manager import GatewayPlaybackManager
except ImportError:
    try:
        from audio.playback_manager import GatewayPlaybackManager
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayPlaybackManager")
        sys.exit(1)

try:
    from gateway.core.call_session_handler import GatewayCallSessionHandler
except ImportError:
    try:
        from core.call_session_handler import GatewayCallSessionHandler
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayCallSessionHandler")
        sys.exit(1)

try:
    from gateway.common.network_manager import GatewayNetworkManager
except ImportError:
    try:
        from common.network_manager import GatewayNetworkManager
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayNetworkManager")
        sys.exit(1)

try:
    from gateway.core.monitor_manager import GatewayMonitorManager, ESLAudioReceiver
except ImportError:
    try:
        from core.monitor_manager import GatewayMonitorManager, ESLAudioReceiver
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayMonitorManager")
        sys.exit(1)

try:
    from gateway.audio.audio_processor import GatewayAudioProcessor
except ImportError:
    try:
        from audio.audio_processor import GatewayAudioProcessor
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayAudioProcessor")
        sys.exit(1)

try:
    from gateway.core.gateway_utils import GatewayUtils
except ImportError:
    try:
        from core.gateway_utils import GatewayUtils
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayUtils")
        sys.exit(1)

try:
    from gateway.core.gateway_event_router import GatewayEventRouter
except ImportError:
    try:
        from core.gateway_event_router import GatewayEventRouter
    except ImportError:
        logging.error("[IMPORT_ERROR] Cannot import GatewayEventRouter")
        sys.exit(1)
from gateway.core.gateway_config_manager import GatewayConfigManager
from gateway.core.gateway_activity_monitor import GatewayActivityMonitor
from gateway.core.gateway_console_manager import GatewayConsoleManager
from gateway.core.gateway_esl_manager import GatewayESLManager
from gateway.core.gateway_component_factory import GatewayComponentFactory
import inspect as _rg_inspect
try:
    os.write(
        2,
        f"[GCF_WHICH] class={GatewayComponentFactory} class_file={_rg_inspect.getsourcefile(GatewayComponentFactory)}\n".encode(),
    )
    os.write(
        2,
        f"[GCF_WHICH] setup_all_components_file={_rg_inspect.getsourcefile(GatewayComponentFactory.setup_all_components)} firstline={_rg_inspect.getsourcelines(GatewayComponentFactory.setup_all_components)[1]}\n".encode(),
    )
except Exception as _rg_inspect_exc:
    os.write(2, f"[GCF_WHICH] inspect_failed err={_rg_inspect_exc!r}\n".encode())
from gateway.asr.gateway_rtp_protocol import RTPPacketBuilder, RTPProtocol
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
from gateway.audio import AudioManager
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

        # ASRマネージャ初期化
        self.asr_manager = GatewayASRManager(self)
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


def main():
    _gw_trace("[gateway_main] started")
    """Main entry point for realtime_gateway"""
    import sys as _rg_sys_main, time as _rg_time_main

    _rg_sys_main.stderr.write(
        f"[RG_MAIN_ENTER] ts={_rg_time_main.time()} entering main\n"
    )
    _rg_sys_main.stderr.flush()
    import argparse
    parser = argparse.ArgumentParser(description="RealtimeGateway for LibertyCall")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--port", type=int, help="Port override")
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    _dump_import_paths()
    
    # Load default config
    config = {
        "rtp": {
            "listen_host": "0.0.0.0",
            "listen_port": 7002,
            "payload_type": 8,
            "sample_rate": 8000
        },
        "asr": {
            "enabled": True
        },
        "ws": {
            "url": "ws://127.0.0.1:8080",
            "reconnect_delay_sec": 5
        }
    }

    return asyncio.run(async_main(config, args.port))


async def async_main(config: dict, port_override: int | None) -> int:
    import sys as _rg_sys_async, time as _rg_time_async, asyncio as _rg_asyncio

    _rg_sys_async.stderr.write(
        f"[RG_ASYNC_MAIN_ENTER] ts={_rg_time_async.time()}\n"
    )
    _rg_sys_async.stderr.flush()

    gateway = RealtimeGateway(config, rtp_port_override=port_override)
    _rg_sys_async.stderr.write(
        f"[RG_CALL_SETUP_ALL] ts={_rg_time_async.time()} gateway_id={id(gateway)} utils_id={id(gateway.utils)}\n"
    )
    _rg_sys_async.stderr.flush()
    try:
        GatewayComponentFactory(gateway.utils).setup_all_components()
        _rg_sys_async.stderr.write(
            f"[RG_SETUP_ALL_DONE] ts={_rg_time_async.time()}\n"
        )
        _rg_sys_async.stderr.flush()
    except Exception as exc:
        _rg_sys_async.stderr.write(
            f"[RG_SETUP_ALL_FAIL] ts={_rg_time_async.time()} err={exc}\n"
        )
        _rg_sys_async.stderr.flush()
        raise

    await _rg_asyncio.sleep(0)  # allow background tasks to start

    print("RealtimeGateway started successfully")
    print("Press Ctrl+C to stop...")

    import socket
    import threading
    import queue

    audio_queue = queue.Queue()

    try:
        from gateway.asr.google_stream_asr import GoogleStreamingASR
        print(f"[DEBUG_MAIN] Creating GoogleStreamingASR instance")
        asr = GoogleStreamingASR()
        print("[DEBUG_MAIN] Instance created")
        print(f"[DEBUG_MAIN] Attempting asr.start with audio_queue type: {type(audio_queue)}")
        asr.start(audio_queue)
        print(f"[DEBUG_SYNC] Queue ID in Main: {id(audio_queue)}")
        print("[DEBUG_MAIN] start() called, entering UDP loop")
        print("[DEBUG_ASR_CONNECT] ASR Stream started")
    except Exception as e:
        print(f"[ERROR_ASR_CONNECT] Failed to start ASR: {e}")
        import traceback
        traceback.print_exc()

    def udp_receiver():
        """UDPパケットを受信し、ASRに転送"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)  # 1MB
        sock.bind(('0.0.0.0', 7002))
        sock.settimeout(1.0)

        print("[DEBUG_RTP_FLOW] UDP receiver listening on 0.0.0.0:7002")
        print("[DEBUG_RTP_FLOW] OS UDP buffer set to 1MB")

        file_queue = queue.Queue(maxsize=1000)

        def file_writer():
            try:
                with open("/tmp/debug_udp_raw.pcm", "ab") as f:
                    while True:
                        try:
                            data = file_queue.get(timeout=1.0)
                            if data is None:
                                break
                            f.write(data)
                            f.flush()
                            file_queue.task_done()
                        except queue.Empty:
                            continue
                        except Exception as err:
                            sys.stdout.write(f"[DEBUG_RTP_FLOW] File write error: {err}\n")
                            sys.stdout.flush()
            except Exception as err:
                sys.stdout.write(f"[DEBUG_RTP_FLOW] File writer init error: {err}\n")
                sys.stdout.flush()

        writer_thread = threading.Thread(target=file_writer, daemon=True)
        writer_thread.start()

        packet_count = 0
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                global _GW_TRACE_CNT
                if _GW_TRACE_CNT < 3:
                    _GW_TRACE_CNT += 1
                    h = " ".join(f"{b:02x}" for b in data[:12])
                    _gw_trace(
                        f"[rtp_recv] n={_GW_TRACE_CNT} from={addr[0]}:{addr[1]} len={len(data)} head12={h}"
                    )
                if len(data) > 0:
                    packet_count += 1
                    try:
                        file_queue.put_nowait(data)
                    except queue.Full:
                        pass
                    audio_queue.put(data)
                    if packet_count % 100 == 0:
                        sys.stdout.write(
                            f"[DEBUG_RTP_FLOW] Received packet #{packet_count} ({len(data)} bytes)\n"
                        )
                        sys.stdout.flush()
            except socket.timeout:
                if int(time.time()) % 10 == 0:
                    print("[ALIVE_CHECK] Waiting for UDP packets on port 7002...")
                continue
            except Exception as err:
                sys.stdout.write(f"[DEBUG_RTP_FLOW] Error receiving: {err}\n")
                sys.stdout.flush()
                break

    print(f"[DEBUG_FLOW] Main loop queue ID: {id(audio_queue)}")
    print("[DEBUG_MAIN] Entering udp_receiver_loop now...")
    sys.stdout.flush()
    _rg_sys_async.stderr.write(
        f"[RG_BEFORE_LOOP] ts={_rg_time_async.time()} entering main while loop\n"
    )
    _rg_sys_async.stderr.flush()
    receiver_thread = threading.Thread(target=udp_receiver, daemon=True)
    receiver_thread.start()

    try:
        while True:
            await _rg_asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    return 0


try:
    import inspect as _rg_inspect
    _rg_main = globals().get("main")
    sys.stderr.write(
        f"[RG_SELF] main_obj={_rg_main} has_main={'main' in globals()} main_file={_rg_inspect.getsourcefile(_rg_main) if _rg_main else None} main_line={_rg_inspect.getsourcelines(_rg_main)[1] if _rg_main else None}\n"
    )
    sys.stderr.flush()
except Exception as _rg_self_exc:  # pragma: no cover - diagnostics only
    sys.stderr.write(f"[RG_SELF_FAIL] err={_rg_self_exc}\n")
    sys.stderr.flush()


sys.stderr.write(
    f"[RG_EOF] ts={time.time()} reached end-of-file name={__name__}\n"
)
sys.stderr.flush()

if __name__ == "__main__":
    sys.stderr.write(f"[RG_CALL_MAIN] ts={time.time()} calling main\n")
    sys.stderr.flush()
    import sys as _rg_sys
    _rg_sys.exit(main())
