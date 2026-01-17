"""TCP/Unix socket server handling for network manager."""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.network_manager import GatewayNetworkManager


class NetworkSocketServer:
    def __init__(self, manager: "GatewayNetworkManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def setup_server_socket(self) -> None:
        """イベントソケットファイルの事前クリーンアップ。"""
        if self.manager.gateway.event_socket_path.exists():
            try:
                self.manager.gateway.event_socket_path.unlink()
                self.logger.info(
                    "[EVENT_SOCKET] Removed existing socket file: %s",
                    self.manager.gateway.event_socket_path,
                )
            except Exception as e:
                self.logger.warning(
                    "[EVENT_SOCKET] Failed to remove existing socket: %s", e
                )

    def cleanup_sockets(self) -> None:
        """イベントソケットファイルの後処理。"""
        if self.manager.gateway.event_socket_path.exists():
            try:
                self.manager.gateway.event_socket_path.unlink()
                self.logger.info(
                    "[EVENT_SOCKET] Removed socket file: %s",
                    self.manager.gateway.event_socket_path,
                )
            except Exception as e:
                self.logger.warning(
                    "[EVENT_SOCKET] Failed to remove socket file: %s", e
                )

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """クライアント接続ハンドラー"""
        gateway = self.manager.gateway
        try:
            while gateway.running:
                # データを受信（JSON形式）
                data = await reader.read(4096)
                if not data:
                    break

                try:
                    message = json.loads(data.decode("utf-8"))
                    event_type = message.get("event")
                    uuid = message.get("uuid")
                    call_id = message.get("call_id")
                    client_id = message.get("client_id", "000")

                    self.logger.info(
                        "[EVENT_SOCKET] Received event: %s uuid=%s call_id=%s",
                        event_type,
                        uuid,
                        call_id,
                    )

                    if event_type == "call_start":
                        # CHANNEL_ANSWERイベント
                        if call_id:
                            # call_idが指定されている場合はそれを使用
                            effective_call_id = call_id
                        elif uuid:
                            # UUIDからcall_idを生成
                            effective_call_id = gateway._generate_call_id_from_uuid(
                                uuid, client_id
                            )
                        else:
                            self.logger.warning(
                                "[EVENT_SOCKET] call_start event missing call_id and uuid"
                            )
                            writer.write(
                                b'{"status": "error", "message": "missing call_id or uuid"}\n'
                            )
                            await writer.drain()
                            continue

                        # UUIDとcall_idのマッピングを保存
                        if uuid and effective_call_id:
                            gateway.call_uuid_map[effective_call_id] = uuid
                            self.logger.info(
                                "[EVENT_SOCKET] Mapped call_id=%s -> uuid=%s",
                                effective_call_id,
                                uuid,
                            )

                        # on_call_start()を呼び出す
                        try:
                            if hasattr(gateway.ai_core, "on_call_start"):
                                gateway.ai_core.on_call_start(
                                    effective_call_id, client_id=client_id
                                )
                                self.logger.info(
                                    "[EVENT_SOCKET] on_call_start() called for call_id=%s client_id=%s",
                                    effective_call_id,
                                    client_id,
                                )
                            else:
                                self.logger.error(
                                    "[EVENT_SOCKET] ai_core.on_call_start() not found"
                                )
                        except Exception as e:
                            self.logger.exception(
                                "[EVENT_SOCKET] Error calling on_call_start(): %s",
                                e,
                            )

                        # RealtimeGateway側の状態を更新
                        self.logger.warning(
                            "[CALL_START_TRACE] [LOC_START] Adding %s to _active_calls (event_socket) at %.3f",
                            effective_call_id,
                            time.time(),
                        )
                        gateway._active_calls.add(effective_call_id)
                        gateway.call_id = effective_call_id
                        gateway.client_id = client_id
                        self.logger.info(
                            "[EVENT_SOCKET] Added call_id=%s to _active_calls, set call_id and client_id=%s",
                            effective_call_id,
                            client_id,
                        )

                        # 初回アナウンス再生処理を実行（非同期タスクとして実行）
                        try:
                            task = asyncio.create_task(
                                gateway._queue_initial_audio_sequence(client_id)
                            )

                            def _log_init_task_result(t):
                                try:
                                    t.result()  # 例外があればここで再送出される
                                except Exception as e:
                                    import traceback

                                    self.logger.error(
                                        "[INIT_TASK_ERR] Initial sequence task failed: %s\n%s",
                                        e,
                                        traceback.format_exc(),
                                    )

                            task.add_done_callback(_log_init_task_result)
                            self.logger.warning(
                                "[INIT_TASK_START] Created task for %s",
                                client_id,
                            )
                            self.logger.info(
                                "[EVENT_SOCKET] _queue_initial_audio_sequence() called for call_id=%s client_id=%s",
                                effective_call_id,
                                client_id,
                            )
                        except Exception as e:
                            self.logger.exception(
                                "[EVENT_SOCKET] Error calling _queue_initial_audio_sequence(): %s",
                                e,
                            )

                        writer.write(b'{"status": "ok"}\n')
                        await writer.drain()

                    elif event_type == "call_end":
                        # CHANNEL_HANGUPイベント
                        effective_call_id = None
                        try:
                            if call_id:
                                effective_call_id = call_id
                            elif uuid:
                                # UUIDからcall_idを逆引き
                                for cid, u in gateway.call_uuid_map.items():
                                    if u == uuid:
                                        effective_call_id = cid
                                        break

                                if not effective_call_id:
                                    self.logger.warning(
                                        "[EVENT_SOCKET] call_end event: uuid=%s not found in call_uuid_map",
                                        uuid,
                                    )
                                    writer.write(
                                        b'{"status": "error", "message": "uuid not found"}\n'
                                    )
                                    await writer.drain()
                                    continue
                            else:
                                self.logger.warning(
                                    "[EVENT_SOCKET] call_end event missing call_id and uuid"
                                )
                                writer.write(
                                    b'{"status": "error", "message": "missing call_id or uuid"}\n'
                                )
                                await writer.drain()
                                continue

                            # on_call_end()を呼び出す
                            try:
                                if hasattr(gateway.ai_core, "on_call_end"):
                                    gateway.ai_core.on_call_end(
                                        effective_call_id,
                                        source="gateway_event_listener",
                                    )
                                    self.logger.info(
                                        "[EVENT_SOCKET] on_call_end() called for call_id=%s",
                                        effective_call_id,
                                    )
                                else:
                                    self.logger.error(
                                        "[EVENT_SOCKET] ai_core.on_call_end() not found"
                                    )
                                # 【追加】通話ごとのASRインスタンスをクリーンアップ
                                if hasattr(gateway.ai_core, "cleanup_asr_instance"):
                                    gateway.ai_core.cleanup_asr_instance(
                                        effective_call_id
                                    )
                                    self.logger.info(
                                        "[EVENT_SOCKET] cleanup_asr_instance() called for call_id=%s",
                                        effective_call_id,
                                    )
                            except Exception as e:
                                self.logger.exception(
                                    "[EVENT_SOCKET] Error calling on_call_end(): %s",
                                    e,
                                )

                            if gateway.call_id == effective_call_id:
                                gateway.call_id = None

                            # UUIDとcall_idのマッピングを削除
                            if effective_call_id in gateway.call_uuid_map:
                                del gateway.call_uuid_map[effective_call_id]

                            writer.write(b'{"status": "ok"}\n')
                            await writer.drain()
                        except Exception as e:
                            self.logger.error(
                                "[EVENT_SOCKET_ERR] Error during call_end processing for call_id=%s: %s",
                                effective_call_id,
                                e,
                                exc_info=True,
                            )
                        finally:
                            # ★どんなエラーがあっても、ここは必ず実行する★
                            self.logger.warning(
                                "[FINALLY_BLOCK_ENTRY] Entered finally block for call_id=%s",
                                effective_call_id,
                            )
                            if effective_call_id:
                                call_end_time = time.time()
                                # _active_calls から削除
                                self.logger.warning(
                                    "[FINALLY_ACTIVE_CALLS] Before removal: call_id=%s in _active_calls=%s",
                                    effective_call_id,
                                    effective_call_id in gateway._active_calls
                                    if hasattr(gateway, "_active_calls")
                                    else False,
                                )
                                if (
                                    hasattr(gateway, "_active_calls")
                                    and effective_call_id in gateway._active_calls
                                ):
                                    gateway._active_calls.remove(effective_call_id)
                                    self.logger.warning(
                                        "[EVENT_SOCKET_DONE] Removed %s from active_calls (finally block) at %.3f",
                                        effective_call_id,
                                        call_end_time,
                                    )
                                self.logger.warning(
                                    "[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id=%s in _active_calls=%s",
                                    effective_call_id,
                                    effective_call_id in gateway._active_calls
                                    if hasattr(gateway, "_active_calls")
                                    else False,
                                )

                                # 管理用データのクリーンアップ
                                if effective_call_id in gateway._recovery_counts:
                                    del gateway._recovery_counts[effective_call_id]
                                if effective_call_id in gateway._initial_sequence_played:
                                    gateway._initial_sequence_played.discard(
                                        effective_call_id
                                    )
                                if effective_call_id in gateway._last_processed_sequence:
                                    del gateway._last_processed_sequence[
                                        effective_call_id
                                    ]
                                gateway._last_voice_time.pop(effective_call_id, None)
                                gateway._last_silence_time.pop(
                                    effective_call_id, None
                                )
                                gateway._last_tts_end_time.pop(
                                    effective_call_id, None
                                )
                                gateway._last_user_input_time.pop(
                                    effective_call_id, None
                                )
                                gateway._silence_warning_sent.pop(
                                    effective_call_id, None
                                )
                                if hasattr(gateway, "_initial_tts_sent"):
                                    gateway._initial_tts_sent.discard(
                                        effective_call_id
                                    )
                                self.logger.debug(
                                    "[CALL_CLEANUP] Cleared state for call_id=%s",
                                    effective_call_id,
                                )
                    else:
                        self.logger.warning(
                            "[EVENT_SOCKET] Unknown event type: %s", event_type
                        )
                        writer.write(
                            b'{"status": "error", "message": "unknown event type"}\n'
                        )
                        await writer.drain()

                except json.JSONDecodeError as e:
                    self.logger.error("[EVENT_SOCKET] Failed to parse JSON: %s", e)
                    writer.write(b'{"status": "error", "message": "invalid json"}\n')
                    await writer.drain()
                except Exception as e:
                    self.logger.exception("[EVENT_SOCKET] Error handling event: %s", e)
                    writer.write(b'{"status": "error", "message": "internal error"}\n')
                    await writer.drain()

        except Exception as e:
            self.logger.exception("[EVENT_SOCKET] Client handler error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def event_socket_server_loop(self) -> None:
        """
        FreeSWITCHイベント受信用Unixソケットサーバー

        gateway_event_listener.pyからイベントを受信して、
        on_call_start() / on_call_end() を呼び出す
        """
        self.setup_server_socket()
        self.logger.info("[EVENT_SOCKET_DEBUG] _event_socket_server_loop started")

        try:
            self.logger.info("[EVENT_SOCKET_DEBUG] About to start unix server")
            # Unixソケットサーバーを起動
            gateway.event_server = await asyncio.start_unix_server(
                self.handle_client,
                str(gateway.event_socket_path),
            )
            self.logger.info(
                "[EVENT_SOCKET] Server started on %s",
                gateway.event_socket_path,
            )
            # サーバーが停止するまで待機
            async with gateway.event_server:
                await gateway.event_server.serve_forever()
        except Exception as e:
            self.logger.error("[EVENT_SOCKET] Server error: %s", e, exc_info=True)
        finally:
            # クリーンアップ
            self.cleanup_sockets()
