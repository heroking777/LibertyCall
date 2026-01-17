#!/usr/bin/env python3
"""Gateway utilities for resource and thread management."""
import asyncio
import collections
import glob
import os
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple


IGNORE_RTP_IPS = {"160.251.170.253", "127.0.0.1", "::1"}


class GatewayUtils:
    def __init__(self, gateway: "RealtimeGateway", rtp_builder_cls, rtp_protocol_cls):
        self.gateway = gateway
        self.logger = gateway.logger
        self.rtp_builder_cls = rtp_builder_cls
        self.rtp_protocol_cls = rtp_protocol_cls

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

    async def start(self):
        gateway = self.gateway
        self.logger.info("[RTP_START] RealtimeGateway.start() called")
        gateway.running = True
        gateway.rtp_builder = self.rtp_builder_cls(
            gateway.payload_type, gateway.sample_rate
        )

        try:
            loop = asyncio.get_running_loop()

            # ソケットをメンバに保持してbind（IPv4固定、0.0.0.0で全インターフェースにバインド）
            # 0.0.0.0 にバインドすることで、FreeSWITCHからのRTPパケットを確実に受信できる
            gateway.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            gateway.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            gateway.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            gateway.rtp_sock.bind(("0.0.0.0", gateway.rtp_port))
            gateway.rtp_sock.setblocking(False)  # asyncio用にノンブロッキングへ
            bound_addr = gateway.rtp_sock.getsockname()
            self.logger.info("[RTP_BIND_FINAL] Bound UDP socket to %s", bound_addr)

            # asyncioにソケットを渡す
            gateway.rtp_transport, _ = await loop.create_datagram_endpoint(
                lambda: self.rtp_protocol_cls(gateway),
                sock=gateway.rtp_sock,
            )
            self.logger.info(
                "[RTP_READY_FINAL] RTP listener active and awaiting packets on %s",
                bound_addr,
            )

            # WebSocketサーバー起動処理
            try:
                ws_task = asyncio.create_task(gateway._ws_server_loop())
                self.logger.info(
                    "[BOOT] WebSocket server startup scheduled on port 9001 (task=%r)",
                    ws_task,
                )
            except Exception as e:
                self.logger.error(
                    "[BOOT] Failed to start WebSocket server: %s", e, exc_info=True
                )

            asyncio.create_task(gateway._ws_client_loop())
            asyncio.create_task(gateway._tts_sender_loop())

            # ストリーミングモード: 定期的にASR結果をポーリング
            if gateway.streaming_enabled:
                asyncio.create_task(gateway._streaming_poll_loop())

            # 無音検出ループ開始（TTS送信後の無音を監視）
            gateway.monitor_manager.start_no_input_monitoring()

            # ログファイル監視ループ開始（転送失敗時のTTSアナウンス用）
            asyncio.create_task(gateway._log_monitor_loop())

            # イベントループ起動後にキューに追加された転送タスクを処理
            # 注意: イベントループが起動した後でないと asyncio.create_task が呼べない
            async def process_queued_transfers():
                while gateway._transfer_task_queue:
                    call_id = gateway._transfer_task_queue.popleft()
                    self.logger.info(
                        "TRANSFER_TASK_PROCESSING: call_id=%s (from queue)", call_id
                    )
                    asyncio.create_task(gateway._wait_for_tts_and_transfer(call_id))
                # 定期的にキューをチェック（新しいタスクが追加される可能性があるため）
                while gateway.running:
                    await asyncio.sleep(0.5)  # 0.5秒間隔でチェック
                    while gateway._transfer_task_queue:
                        call_id = gateway._transfer_task_queue.popleft()
                        self.logger.info(
                            "TRANSFER_TASK_PROCESSING: call_id=%s (from queue, delayed)",
                            call_id,
                        )
                        asyncio.create_task(
                            gateway._wait_for_tts_and_transfer(call_id)
                        )

            asyncio.create_task(process_queued_transfers())

            # FreeSWITCH送信RTPポート監視を開始（pull型ASR用）
            # record_session方式では不要なため、条件付きで実行
            if gateway.monitor_manager.fs_rtp_monitor:
                gateway.monitor_manager.start_rtp_monitoring()

            # FreeSWITCHイベント受信用Unixソケットサーバーを起動
            self.logger.info("[EVENT_SOCKET_DEBUG] Creating event server task")
            asyncio.create_task(gateway._event_socket_server_loop())

            # サービスを維持（停止イベントを待つ）
            await gateway.shutdown_event.wait()

        except Exception as e:
            self.logger.error("[RTP_BIND_ERROR_FINAL] %s", e, exc_info=True)
        finally:
            if hasattr(gateway, "rtp_transport") and gateway.rtp_transport:
                self.logger.info("[RTP_EXIT_FINAL] Closing RTP transport")
                gateway.rtp_transport.close()
            if hasattr(gateway, "rtp_sock") and gateway.rtp_sock:
                gateway.rtp_sock.close()
                self.logger.info("[RTP_EXIT_FINAL] Socket closed")

    async def shutdown(self, remove_handler_fn=None) -> None:
        gateway = self.gateway
        self.logger.info("[SHUTDOWN] Starting graceful shutdown...")
        gateway.running = False
        gateway._complete_console_call()

        if gateway.websocket:
            try:
                await gateway.websocket.close()
                self.logger.debug("[SHUTDOWN] WebSocket closed")
            except Exception as e:
                self.logger.warning(
                    "[SHUTDOWN] Error while closing WebSocket: %s", e
                )

        if gateway.rtp_transport:
            try:
                self.logger.info("[SHUTDOWN] Closing RTP transport...")
                gateway.rtp_transport.close()
                await asyncio.sleep(0.1)
                self.logger.info("[SHUTDOWN] RTP transport closed")
            except Exception as e:
                self.logger.error(
                    "[SHUTDOWN] Error while closing RTP transport: %s", e
                )

        for call_id, timer_task in list(gateway._no_input_timers.items()):
            if timer_task and not timer_task.done():
                try:
                    timer_task.cancel()
                    self.logger.debug(
                        "[SHUTDOWN] Cancelled no_input_timer for call_id=%s",
                        call_id,
                    )
                except Exception as e:
                    self.logger.warning(
                        "[SHUTDOWN] Error cancelling timer for call_id=%s: %s",
                        call_id,
                        e,
                    )
        gateway._no_input_timers.clear()

        if gateway.call_id and remove_handler_fn:
            try:
                remove_handler_fn(gateway.call_id)
                self.logger.info(
                    "[SHUTDOWN] ASR handler removed for call_id=%s",
                    gateway.call_id,
                )
            except Exception as e:
                self.logger.warning(
                    "[SHUTDOWN] Error removing ASR handler: %s", e
                )

        if gateway.event_server:
            try:
                self.logger.info("[SHUTDOWN] Closing event socket server...")
                gateway.event_server.close()
                await gateway.event_server.wait_closed()
                self.logger.info("[SHUTDOWN] Event socket server closed")
            except Exception as e:
                self.logger.warning(
                    "[SHUTDOWN] Error closing event socket server: %s", e
                )

        if gateway.event_socket_path.exists():
            try:
                gateway.event_socket_path.unlink()
                self.logger.info(
                    "[SHUTDOWN] Removed socket file: %s", gateway.event_socket_path
                )
            except Exception as e:
                self.logger.warning(
                    "[SHUTDOWN] Error removing socket file: %s", e
                )

        gateway.shutdown_event.set()
        self.logger.info("[SHUTDOWN] Graceful shutdown completed")

    def complete_console_call(self) -> None:
        gateway = self.gateway
        if not gateway.console_bridge.enabled or not gateway.call_id or gateway.call_completed:
            return
        call_id_to_complete = gateway.call_id
        try:
            gateway.console_bridge.complete_call(
                call_id_to_complete, ended_at=datetime.utcnow()
            )
            if gateway.streaming_enabled:
                gateway.ai_core.reset_call(call_id_to_complete)
            if hasattr(gateway.ai_core, "on_call_end"):
                gateway.ai_core.on_call_end(
                    call_id_to_complete, source="_complete_console_call"
                )
            if hasattr(gateway.ai_core, "cleanup_asr_instance"):
                gateway.ai_core.cleanup_asr_instance(call_id_to_complete)
            gateway.call_completed = True
            gateway.call_id = None
            gateway.recent_dialogue.clear()
            gateway.transfer_notified = False
            gateway.last_audio_level_sent = 0.0
            gateway.last_audio_level_time = 0.0
        except Exception as e:
            self.logger.error(
                "[COMPLETE_CALL_ERR] Error during _complete_console_call for call_id=%s: %s",
                call_id_to_complete,
                e,
                exc_info=True,
            )
        finally:
            self.logger.warning(
                "[FINALLY_BLOCK_ENTRY] Entered finally block for call_id=%s",
                call_id_to_complete,
            )
            if call_id_to_complete:
                complete_time = time.time()
                self.logger.warning(
                    "[FINALLY_ACTIVE_CALLS] Before removal: call_id=%s in _active_calls=%s",
                    call_id_to_complete,
                    call_id_to_complete in gateway._active_calls
                    if hasattr(gateway, "_active_calls")
                    else False,
                )
                if (
                    hasattr(gateway, "_active_calls")
                    and call_id_to_complete in gateway._active_calls
                ):
                    gateway._active_calls.remove(call_id_to_complete)
                    self.logger.warning(
                        "[COMPLETE_CALL_DONE] Removed %s from active_calls (finally block) at %.3f",
                        call_id_to_complete,
                        complete_time,
                    )
                self.logger.warning(
                    "[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id=%s in _active_calls=%s",
                    call_id_to_complete,
                    call_id_to_complete in gateway._active_calls
                    if hasattr(gateway, "_active_calls")
                    else False,
                )

                if call_id_to_complete in gateway._recovery_counts:
                    del gateway._recovery_counts[call_id_to_complete]
                if call_id_to_complete in gateway._initial_sequence_played:
                    gateway._initial_sequence_played.discard(call_id_to_complete)
                if call_id_to_complete in gateway._last_processed_sequence:
                    del gateway._last_processed_sequence[call_id_to_complete]
                gateway._last_voice_time.pop(call_id_to_complete, None)
                gateway._last_silence_time.pop(call_id_to_complete, None)
                gateway._last_tts_end_time.pop(call_id_to_complete, None)
                gateway._last_user_input_time.pop(call_id_to_complete, None)
                gateway._silence_warning_sent.pop(call_id_to_complete, None)
                if hasattr(gateway, "_initial_tts_sent"):
                    gateway._initial_tts_sent.discard(call_id_to_complete)
                self.logger.debug(
                    "[CALL_CLEANUP] Cleared state for call_id=%s",
                    call_id_to_complete,
                )
        gateway.user_turn_index = 0
        gateway.call_start_time = None
        gateway._reset_call_state()

    def reset_call_state(self) -> None:
        gateway = self.gateway
        was_playing = gateway.initial_sequence_playing
        gateway.initial_sequence_played = False
        gateway.initial_sequence_playing = False
        gateway.initial_sequence_completed = False
        gateway.initial_sequence_completed_time = None
        if gateway._asr_enable_timer:
            try:
                gateway._asr_enable_timer.cancel()
            except Exception:
                pass
            gateway._asr_enable_timer = None
        if was_playing:
            self.logger.info(
                "[INITIAL_SEQUENCE] OFF: call state reset (initial_sequence_playing=False)"
            )
        gateway.tts_queue.clear()
        gateway.is_speaking_tts = False
        gateway.audio_buffer = bytearray()
        gateway.current_segment_start = None
        gateway.is_user_speaking = False
        gateway.last_voice_time = time.time()
        gateway.rtp_peer = None
        gateway._rtp_src_addr = None
        gateway.rtp_packet_count = 0
        gateway.last_rtp_packet_time = 0.0
        gateway._last_tts_text = None

        gateway._stream_chunk_counter = 0
        gateway._last_feed_time = time.time()

        old_call_id = gateway.call_id
        gateway.call_id = None
        gateway.call_start_time = None
        gateway.user_turn_index = 0
        gateway.call_completed = False
        gateway.transfer_notified = False
        gateway.recent_dialogue.clear()

        if old_call_id:
            gateway._last_user_input_time.pop(old_call_id, None)
            gateway._last_tts_end_time.pop(old_call_id, None)
            gateway._no_input_elapsed.pop(old_call_id, None)
            if old_call_id in gateway._no_input_timers:
                timer_task = gateway._no_input_timers.pop(old_call_id)
                if timer_task and not timer_task.done():
                    timer_task.cancel()

        if hasattr(gateway.ai_core, "set_call_id"):
            gateway.ai_core.set_call_id(None)
        if hasattr(gateway.ai_core, "call_id"):
            gateway.ai_core.call_id = None
        if hasattr(gateway.ai_core, "log_session_id"):
            gateway.ai_core.log_session_id = None

        if old_call_id:
            self.logger.info(
                "[RESET_CALL_STATE] call_id reset: %s -> None", old_call_id
            )

        gateway._stop_recording()

    def _free_port(self, port: int):
        """安全にポートを解放する（自分自身は殺さない）"""
        try:
            # まずポートが使用中かチェック
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                sock.close()
                self.logger.debug("[BOOT] Port %s is available", port)
                return  # ポートが空いているので何もしない
        except OSError as e:
            if e.errno == 98:  # Address already in use
                self.logger.warning(
                    "[BOOT] Port %s is in use, attempting to free it...", port
                )
                try:
                    # fuserでポートを使用しているプロセスのPIDを取得
                    res = subprocess.run(
                        ["fuser", f"{port}/tcp"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if not res.stdout.strip():
                        self.logger.debug(
                            "[BOOT] Port %s appears to be free now", port
                        )
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
                        self.logger.info(
                            "[BOOT] Port %s in use by current process only (PID %s) — skipping kill",
                            port,
                            current_pid,
                        )
                        return

                    # 自分以外のプロセスのみKILL
                    pid_strs = [str(pid) for pid in target_pids]
                    subprocess.run(
                        ["kill", "-9"] + pid_strs,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                    self.logger.info(
                        "[BOOT] Port %s freed by killing PIDs: %s",
                        port,
                        ", ".join(pid_strs),
                    )

                    # 少し待機してから再確認
                    time.sleep(0.5)
                except Exception as free_error:
                    self.logger.warning(
                        "[BOOT] Port free check failed: %s", free_error
                    )
            else:
                self.logger.warning("[BOOT] Error checking port %s: %s", port, e)

    def _recover_esl_connection(self, max_retries: int = 3) -> bool:
        """
        FreeSWITCH ESL接続を自動リカバリ（接続が切れた場合に再接続を試みる、最大3回リトライ）

        :param max_retries: 最大リトライ回数（デフォルト: 3）
        :return: 再接続に成功したかどうか
        """
        gateway = self.gateway
        if gateway.esl_connection and gateway.esl_connection.connected():
            return True  # 既に接続されている場合は成功として返す

        self.logger.warning(
            "[ESL_RECOVERY] ESL connection lost, attempting to reconnect (max_retries=%s)...",
            max_retries,
        )

        for attempt in range(1, max_retries + 1):
            try:
                time.sleep(3)  # 3秒待機してから再接続
                gateway._init_esl_connection()

                if gateway.esl_connection and gateway.esl_connection.connected():
                    self.logger.info(
                        "[ESL_RECOVERY] ESL connection recovered successfully (attempt %s/%s)",
                        attempt,
                        max_retries,
                    )
                    # イベントリスナーも再起動
                    if (
                        hasattr(gateway, "esl_listener_thread")
                        and gateway.esl_listener_thread
                        and not gateway.esl_listener_thread.is_alive()
                    ):
                        gateway._start_esl_event_listener()
                    return True
                else:
                    self.logger.warning(
                        "[ESL_RECOVERY] ESL reconnection failed (attempt %s/%s)",
                        attempt,
                        max_retries,
                    )
            except Exception as e:
                self.logger.exception(
                    "[ESL_RECOVERY] Failed to recover ESL connection (attempt %s/%s): %s",
                    attempt,
                    max_retries,
                    e,
                )

        self.logger.error(
            "[ESL_RECOVERY] ESL reconnection failed after %s attempts", max_retries
        )
        return False

    def _start_esl_event_listener(self) -> None:
        """
        FreeSWITCH ESLイベントリスナーを開始（CHANNEL_EXECUTE_COMPLETE監視）

        :return: None
        """
        gateway = self.gateway
        if not gateway.esl_connection or not gateway.esl_connection.connected():
            self.logger.warning(
                "[ESL_LISTENER] ESL not available, event listener not started"
            )
            return

        def _esl_event_listener_worker():
            """ESLイベントリスナーのワーカースレッド（自動リカバリ対応）"""
            try:
                from libs.esl.ESL import ESLevent

                # CHANNEL_EXECUTE_COMPLETEイベントを購読
                gateway.esl_connection.events("plain", "CHANNEL_EXECUTE_COMPLETE")
                self.logger.info(
                    "[ESL_LISTENER] Started listening for CHANNEL_EXECUTE_COMPLETE events"
                )

                consecutive_errors = 0
                max_consecutive_errors = 5

                while gateway.running:
                    try:
                        # ESL接続が切れている場合は自動リカバリを試みる
                        if (
                            not gateway.esl_connection
                            or not gateway.esl_connection.connected()
                        ):
                            self.logger.warning(
                                "[ESL_LISTENER] ESL connection lost, attempting recovery..."
                            )
                            self._recover_esl_connection()
                            if (
                                not gateway.esl_connection
                                or not gateway.esl_connection.connected()
                            ):
                                time.sleep(3)  # 再接続に失敗した場合は3秒待機
                                continue
                            # 再接続成功時はイベント購読を再設定
                            gateway.esl_connection.events(
                                "plain", "CHANNEL_EXECUTE_COMPLETE"
                            )
                            consecutive_errors = 0

                        # イベントを受信（タイムアウト: 1秒）
                        event = gateway.esl_connection.recvEventTimed(1000)

                        if not event:
                            consecutive_errors = 0  # タイムアウトはエラーではない
                            continue

                        event_name = event.getHeader("Event-Name")
                        if event_name != "CHANNEL_EXECUTE_COMPLETE":
                            continue

                        application = event.getHeader("Application")
                        if application != "playback":
                            continue

                        uuid = event.getHeader("Unique-ID") or event.getHeader(
                            "Channel-Call-UUID"
                        )
                        if not uuid:
                            continue

                        # 再生完了を検知: is_playing[uuid] = False に更新
                        if hasattr(gateway.ai_core, "is_playing"):
                            if gateway.ai_core.is_playing.get(uuid, False):
                                gateway.ai_core.is_playing[uuid] = False
                                self.logger.info(
                                    "[ESL_LISTENER] Playback completed: uuid=%s is_playing[%s] = False",
                                    uuid,
                                    uuid,
                                )

                        consecutive_errors = 0  # 成功時はエラーカウントをリセット

                    except Exception as e:
                        consecutive_errors += 1
                        if gateway.running:
                            self.logger.exception(
                                "[ESL_LISTENER] Error processing event (consecutive_errors=%s): %s",
                                consecutive_errors,
                                e,
                            )

                        # 連続エラーが一定回数を超えた場合は自動リカバリを試みる
                        if consecutive_errors >= max_consecutive_errors:
                            self.logger.warning(
                                "[ESL_LISTENER] Too many consecutive errors (%s), attempting recovery...",
                                consecutive_errors,
                            )
                            self._recover_esl_connection()
                            consecutive_errors = 0

                        time.sleep(0.1)
            except Exception as e:
                self.logger.exception(
                    "[ESL_LISTENER] Event listener thread error: %s", e
                )
                # スレッドがクラッシュした場合、3秒後に再起動を試みる
                if gateway.running:
                    self.logger.warning(
                        "[ESL_LISTENER] Event listener thread crashed, will restart in 3 seconds..."
                    )

                    def _restart_listener():
                        time.sleep(3)
                        if gateway.running:
                            gateway._start_esl_event_listener()

                    threading.Thread(
                        target=_restart_listener, daemon=True
                    ).start()

        # イベントリスナースレッドを開始
        gateway.esl_listener_thread = threading.Thread(
            target=_esl_event_listener_worker, daemon=True
        )
        gateway.esl_listener_thread.start()
        self.logger.info("[ESL_LISTENER] ESL event listener thread started")

    def _update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
        return self.gateway.session_handler._update_uuid_mapping_directly(call_id)

    def _find_rtp_info_by_port(self, rtp_port: int) -> Optional[str]:
        """
        RTP port からファイルを探して UUID を返す

        :param rtp_port: RTP port番号
        :return: UUID または None
        """
        try:
            # 全ての rtp_info ファイルを検索
            rtp_info_files = glob.glob("/tmp/rtp_info_*.txt")

            self.logger.debug(
                "[RTP_INFO_SEARCH] port=%s total_files=%s",
                rtp_port,
                len(rtp_info_files),
            )

            for filepath in rtp_info_files:
                try:
                    with open(filepath, "r") as f:
                        content = f.read()

                        # port が含まれるかチェック（local または remote）
                        if f":{rtp_port}" in content:
                            # UUID を抽出
                            for line in content.split("\n"):
                                if line.startswith("uuid="):
                                    uuid = line.split("=", 1)[1].strip()
                                    self.logger.info(
                                        "[RTP_INFO_FOUND] port=%s file=%s uuid=%s",
                                        rtp_port,
                                        filepath,
                                        uuid,
                                    )
                                    return uuid

                except Exception as e:
                    self.logger.debug(
                        "[RTP_INFO_READ_ERROR] file=%s error=%s", filepath, e
                    )
                    continue

            self.logger.warning(
                "[RTP_INFO_NOT_FOUND] No file found for port=%s searched_files=%s",
                rtp_port,
                len(rtp_info_files),
            )
            return None

        except Exception as e:
            self.logger.exception(
                "[RTP_INFO_SEARCH_ERROR] port=%s error=%s", rtp_port, e
            )
            return None

    def _get_effective_call_id(
        self, addr: Optional[Tuple[str, int]] = None
    ) -> Optional[str]:
        """
        RTP受信時に有効なcall_idを決定する。

        :param addr: RTP送信元のアドレス (host, port)。Noneの場合は既存のロジックを使用
        :return: 有効なcall_id、見つからない場合はNone
        """
        gateway = self.gateway
        # アドレスが指定されている場合は、アドレス紐づけを優先
        if addr and hasattr(gateway, "_call_addr_map") and addr in gateway._call_addr_map:
            return gateway._call_addr_map[addr]

        # すでにアクティブ通話が1件のみの場合はそれを使う
        if hasattr(gateway, "_active_calls") and len(gateway._active_calls) == 1:
            return next(iter(gateway._active_calls))

        # アクティブな通話がある場合は最後に開始された通話を使用
        if hasattr(gateway, "_active_calls") and gateway._active_calls:
            active = list(gateway._active_calls)
            if active:
                return active[-1]  # 最後に開始された通話を使用

        # 既存のロジック（call_idが未設定の場合は正式なcall_idを生成）
        if not gateway.call_id:
            # call_idが未設定の場合は正式なcall_idを生成
            if gateway.client_id:
                gateway.call_id = gateway.console_bridge.issue_call_id(gateway.client_id)
                self.logger.debug("Generated call_id: %s", gateway.call_id)
                # AICoreにcall_idを設定
                if gateway.call_id:
                    gateway.ai_core.set_call_id(gateway.call_id)
            else:
                # client_idが未設定の場合はデフォルト値を使用（警告を出さない）
                effective_client_id = gateway.default_client_id or "000"
                gateway.call_id = gateway.console_bridge.issue_call_id(
                    effective_client_id
                )
                self.logger.debug(
                    "Generated call_id: %s using default client_id=%s",
                    gateway.call_id,
                    effective_client_id,
                )
                # AICoreにcall_idを設定
                if gateway.call_id:
                    gateway.ai_core.set_call_id(gateway.call_id)
                    # client_idも設定
                    gateway.client_id = effective_client_id
                    self.logger.debug(
                        "Set client_id to default: %s", effective_client_id
                    )

        return gateway.call_id

    def _maybe_send_audio_level(self, rms: int) -> None:
        """RMS値を正規化して、一定間隔で音量レベルを管理画面に送信。"""
        gateway = self.gateway
        if not gateway.console_bridge.enabled or not gateway.call_id:
            return

        now = time.time()
        # RMSを0.0〜1.0に正規化
        normalized_level = min(1.0, rms / gateway.RMS_MAX)

        # 送信間隔チェック
        time_since_last = now - gateway.last_audio_level_time
        if time_since_last < gateway.AUDIO_LEVEL_INTERVAL:
            return

        # レベル変化が小さい場合は送らない（スパム防止）
        level_diff = abs(normalized_level - gateway.last_audio_level_sent)
        if level_diff < gateway.AUDIO_LEVEL_THRESHOLD and normalized_level < 0.1:
            return

        # 送信
        gateway.console_bridge.send_audio_level(
            gateway.call_id,
            normalized_level,
            direction="user",
            client_id=gateway.client_id,
        )
        gateway.last_audio_level_sent = normalized_level
        gateway.last_audio_level_time = now
