"""Gatewayコンポーネントファクトリー"""
from __future__ import annotations

import asyncio
import inspect
import os
import logging
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

os.write(2, b"[FACTORY_LOADED] ComponentFactory module loading...\n")

os.write(2, f"{time.time():.3f} [GCF_STDERR] MODULE_LOADED file={__file__}\n".encode())


def _stderr(msg: str) -> None:
    try:
        os.write(2, f"{time.time():.3f} [GCF_STDERR] {msg}\n".encode())
    except Exception:
        pass


def _evt(msg: str) -> None:
    try:
        os.write(2, f"{time.time():.3f} [GCF_EVT] {msg}\n".encode())
    except Exception:
        pass


def _which(fn):
    try:
        src = inspect.getsourcefile(fn)
        line = inspect.getsourcelines(fn)[1]
    except Exception:
        src, line = "?", -1
    return f"obj={fn!r} id=0x{id(fn):x} src={src}:{line}"

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.core.gateway_utils import GatewayUtils


class GatewayComponentFactory:
    """Gatewayコンポーネントの初期化を担当"""
    
    def __init__(self, utils: "GatewayUtils"):
        self.utils = utils
        self.gateway = utils.gateway
        self.logger = logging.getLogger(__name__)
    
    def setup_recording(self) -> None:
        """録音機能のセットアップ"""
        recordings_dir = Path(os.getenv("LC_RECORDINGS_DIR", "/opt/libertycall/recordings"))
        if os.getenv("LC_ENABLE_RECORDING", "false").lower() == "true":
            self.gateway.recordings_enabled = True
            self.gateway.recordings_dir = recordings_dir
            recordings_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(
                "録音機能が有効です。録音ファイルは %s に保存されます。",
                recordings_dir,
            )
    
    def setup_websocket(self) -> None:
        """WebSocketサーバーのセットアップ"""
        try:
            ws_task = asyncio.create_task(self.gateway._ws_server_loop())
            self.logger.info(
                "[BOOT] WebSocket server startup scheduled on port 9001 (task=%r)",
                ws_task,
            )
        except Exception as e:
            self.logger.error(
                "[BOOT] Failed to start WebSocket server: %s", e, exc_info=True
            )
    
    def setup_background_tasks(self) -> None:
        """バックグラウンドタスクのセットアップ"""
        asyncio.create_task(self.gateway._ws_client_loop())
        asyncio.create_task(self.gateway._tts_sender_loop())
        
        # ストリーミングモード: 定期的にASR結果をポーリング
        if hasattr(self.gateway, 'streaming_enabled') and self.gateway.streaming_enabled:
            asyncio.create_task(self.gateway._streaming_poll_loop())
        
        # 無音検出ループ開始（TTS送信後の無音を監視）
        self.gateway.monitor_manager.start_no_input_monitoring()
        
        # ログファイル監視ループ開始（転送失敗時のTTSアナウンス用）
    
    def setup_asr_components(self) -> None:
        """ASRコンポーネントのセットアップ"""
        import os  # 明示的にインポート
        
        # テスト用ログ
        with open('/tmp/factory_test.log', 'a') as f:
            f.write(f"[FACTORY_TEST] os available: {os is not None}\n")
            f.write(f"[FACTORY_TEST] provider: {os.environ.get('LC_ASR_PROVIDER', 'NOT_SET')}\n")
        
        provider = os.environ.get('LC_ASR_PROVIDER', 'NOT_SET')
        
        if provider == 'google':
            try:
                with open('/tmp/factory_test.log', 'a') as f:
                    f.write("[FACTORY_TEST] Importing GoogleStreamingASR\n")
                from gateway.asr.google_stream_asr import GoogleStreamingASR
                
                # GoogleStreamingASRを生成
                call_id = getattr(self.gateway, 'call_id', 'unknown')
                with open('/tmp/factory_test.log', 'a') as f:
                    f.write(f"[FACTORY_TEST] Creating GoogleStreamingASR with call_id={call_id}\n")
                
                # ASR入口ログ
                try:
                    with open('/tmp/gateway_google_asr.trace', 'a') as f:
                        f.write(f"[ASR_FACTORY_BEFORE] call_id={call_id}\n")
                except Exception:
                    pass
                
                stream_handler = GoogleStreamingASR()
                
                # ASR入口ログ
                try:
                    with open('/tmp/gateway_google_asr.trace', 'a') as f:
                        f.write(f"[ASR_FACTORY_AFTER] asr_class={stream_handler.__class__.__name__} module={stream_handler.__class__.__module__}\n")
                except Exception:
                    pass
                
                # 実体ダンプ（1行だけ）
                try:
                    import inspect
                    sig = str(inspect.signature(stream_handler._client.streaming_recognize))
                    with open('/tmp/gateway_google_asr.trace', 'a') as f:
                        f.write(f"[ASR_ENTRYPOINT] file={stream_handler.__class__.__module__} GoogleStreamASR_src={inspect.getsourcefile(GoogleStreamingASR)} client_sig={sig}\n")
                except Exception:
                    pass
                
                with open('/tmp/factory_test.log', 'a') as f:
                    f.write("[FACTORY_TEST] GoogleStreamingASR created successfully\n")
                
                # asr_managerに注入
                if hasattr(self.gateway, 'asr_manager') and self.gateway.asr_manager:
                    processor = self.gateway.asr_manager.audio_processor
                    processor.stream_handler = stream_handler
                    stream_handler.start_stream()
                    self.logger.info("[ASR_SETUP] stream_handler injected successfully")
                else:
                    self.logger.error("[ASR_SETUP] asr_manager not available")
            except Exception as e:
                with open('/tmp/factory_test.log', 'a') as f:
                    f.write(f"[FACTORY_ERROR] {type(e).__name__}: {e}\n")
                self.logger.error(f"[ASR_SETUP] Failed to setup GoogleStreamingASR: {e}", exc_info=True)
        else:
            self.logger.error(f"[ASR_SETUP] Unsupported provider: {provider}")
    
    def setup_all_components(self) -> None:
        """全てのコンポーネントをセットアップ"""

        # [PATCH] Ensure event loop exists
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            # print("[FAC_PATCH] Created new event loop")
        _evt(
            f"setup_all_components ENTER gateway_id={id(self.gateway)} running="
            f"{getattr(self.gateway, 'running', None)}"
        )
        _evt("bound self.setup_event_server => " + _which(self.setup_event_server))
        if hasattr(self, "setup_event_socket"):
            _evt("bound self.setup_event_socket => " + _which(self.setup_event_socket))
        for name in ["enable_event_server", "event_server_enabled", "enable_events"]:
            if hasattr(self.gateway, name):
                _evt(f"gateway.{name}={getattr(self.gateway, name)!r}")
            if hasattr(self, name):
                _evt(f"factory.{name}={getattr(self, name)!r}")
        _stderr("setup_all_components ENTER")
        self.logger.info("[GCF_SETUP_ALL_ENTER] factory_id=%s gateway_id=%s", id(self), id(self.gateway))
        with open('/tmp/gateway_chain.log', 'a') as f:
            f.write("[FAC_1] setup_all_components start\n")
        try:
            self.setup_recording()
            self.setup_websocket()
            self.setup_background_tasks()
            self.setup_transfer_processor()
            self.setup_asr_components()
            _evt("FORCE calling self.setup_event_server() now")
            self.setup_event_server()
            _evt("FORCE called self.setup_event_server() done")
            self.logger.info("[GCF_SETUP_ALL_DONE]")
            with open('/tmp/gateway_chain.log', 'a') as f:
                f.write("[FAC_2] All components setup completed\n")
            _evt("setup_all_components DONE")
            _stderr("setup_all_components EXIT")
        except Exception as e:
            with open('/tmp/gateway_chain.log', 'a') as f:
                f.write(f"[FAC_ERROR] {type(e).__name__}: {e}\n")
            _stderr(f"setup_all_components FAIL err={e!r}")
            _evt(f"setup_all_components FAIL err={e!r}")
            self.logger.error(f"[FACTORY_ERROR] Setup failed: {e}", exc_info=True)

    
    def setup_recording(self) -> None:
        """録音コンポーネントをセットアップ"""
        self.logger.info("[FACTORY] Setting up recording components")
    
    def setup_event_socket(self) -> None:
        """イベントソケットをセットアップ"""
        self.logger.info("[FACTORY] Setting up event socket")
    
    def setup_websocket(self) -> None:
        """WebSocketをセットアップ"""
        self.logger.info("[FACTORY] Setting up WebSocket")
    
    def setup_background_tasks(self) -> None:
        """バックグラウンドタスクをセットアップ"""
        self.logger.info("[FACTORY] Setting up background tasks")
        
        async def process_queued_transfers():
            # 転送処理の実装
            pass
        
        asyncio.create_task(process_queued_transfers())
    
    def setup_transfer_processor(self) -> None:
        """転送プロセッサーをセットアップ"""
        self.logger.info("[FACTORY] Setting up transfer processor")
        
        def _handle_transfer(call_id: str):
            # 転送処理の実装
            self.logger.info(
                "[TRANSFER_QUEUE] Processing queued transfer for call_id=%s",
                call_id,
            )
            self._handle_transfer(call_id)
        
        async def process_queued_transfers():
            while self.gateway._transfer_task_queue:
                call_id = self.gateway._transfer_task_queue.popleft()
                self.logger.info(
                    "[TRANSFER_QUEUE] Processing queued transfer for call_id=%s",
                    call_id,
                )
                self._handle_transfer(call_id)
        
        asyncio.create_task(process_queued_transfers())
    
    def setup_monitoring_components(self) -> None:
        """監視コンポーネントのセットアップ"""
        # ログファイル監視ループ開始（転送失敗時のTTSアナウンス用）
        asyncio.create_task(self.gateway._log_monitor_loop())
        
        # FreeSWITCH送信RTPポート監視を開始（pull型ASR用）
        if self.gateway.monitor_manager.fs_rtp_monitor:
            self.gateway.monitor_manager.start_rtp_monitoring()
    
    def setup_event_server(self) -> None:
        """イベントサーバーのセットアップ"""
        # FreeSWITCHイベント受信用Unixソケットサーバーを起動
        _stderr("setup_event_server ENTER")
        _evt(
            f"setup_event_server ENTER path={getattr(self.gateway, 'event_socket_path', None)}"
            f" running={getattr(self.gateway, 'running', None)}"
        )
        if not getattr(self.gateway, "event_socket_path", None):
            self.gateway.event_socket_path = Path("/tmp/liberty_gateway_events.sock")
        if getattr(self.gateway, "event_server", None) is None:
            self.gateway.event_server = None
        existing_task = getattr(self.gateway, "_event_socket_server_task", None)
        if existing_task and not existing_task.done():
            _evt(
                f"setup_event_server SKIP existing_task id=0x{id(existing_task):x} done={existing_task.done()}"
            )
            return
        invocation_count = getattr(self.gateway, "_event_server_invocations", 0) + 1
        self.gateway._event_server_invocations = invocation_count
        _evt(f"setup_event_server INVOCATION_COUNT={invocation_count}")
        self.logger.info(
            "[GCF_SETUP_EVENT_ENTER] event_socket_path=%s",
            getattr(self.gateway, "event_socket_path", None),
        )

        async def _log_task_completion(task: asyncio.Task) -> None:
            try:
                await task
                self.logger.info("[GCF_SETUP_EVENT_TASK_DONE] task_id=%s", id(task))
            except Exception as exc:  # pragma: no cover - diagnostics only
                self.logger.error(
                    "[GCF_SETUP_EVENT_TASK_FAIL] task_id=%s err=%s",
                    id(task),
                    exc,
                    exc_info=True,
                )

        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(self.gateway._event_socket_server_loop())
            task_id = id(task)
            self.logger.info("[GCF_SETUP_EVENT_TASK_CREATED] task_id=%s", task_id)
            _stderr(f"setup_event_server TASK_CREATED id={task_id}")
            _evt(
                f"setup_event_server TASK_CREATED id={task_id} loop_running={loop.is_running()} done={task.done()}"
            )
            self.gateway._event_socket_server_task = task

            def _done_wrapper(t: asyncio.Task) -> None:
                try:
                    exc = t.exception()
                    _stderr(f"setup_event_server TASK_DONE id={id(t)} exc={exc!r}")
                    if exc:
                        _evt(f"setup_event_server TASK_DONE id={id(t)} exc={exc!r}")
                        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                        os.write(2, trace.encode())
                    else:
                        _evt(f"setup_event_server TASK_DONE id={id(t)} exc=None")
                except Exception as done_exc:  # pragma: no cover
                    _stderr(f"setup_event_server TASK_DONE exception_check_failed err={done_exc!r}")
                    _evt(f"setup_event_server TASK_DONE exception_check_failed err={done_exc!r}")

            task.add_done_callback(_done_wrapper)
            asyncio.create_task(_log_task_completion(task))
        except Exception as exc:
            _stderr(f"setup_event_server FAIL err={exc!r}")
            _evt(f"setup_event_server FAIL err={exc!r}")
            self.logger.error("[GCF_SETUP_EVENT_CREATE_FAIL] %s", exc, exc_info=True)

    def setup_event_socket(self) -> None:
        _evt("setup_event_socket alias called -> setup_event_server")
        return self.setup_event_server()
