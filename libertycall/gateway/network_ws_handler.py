"""WebSocket client/server handling for network manager."""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import websockets

from libertycall.client_loader import load_client_profile

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.network_manager import GatewayNetworkManager


class NetworkWSHandler:
    def __init__(self, manager: "GatewayNetworkManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    async def ws_client_loop(self) -> None:
        gateway = self.manager.gateway
        while gateway.running:
            try:
                async with websockets.connect(gateway.ws_url) as websocket:
                    gateway.websocket = websocket
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
                                        req_caller_number = data.get(
                                            "caller_number"
                                        )  # caller_numberを取得
                                        self.logger.debug(
                                            "[Init] Request for client_id: %s",
                                            req_client_id,
                                        )

                                        # プロファイル読み込み
                                        gateway.client_profile = load_client_profile(
                                            req_client_id
                                        )

                                        # メモリ展開
                                        if gateway.call_id and (
                                            gateway.client_id != req_client_id
                                            or (
                                                req_call_id
                                                and gateway.call_id != req_call_id
                                            )
                                        ):
                                            gateway._complete_console_call()
                                        gateway._reset_call_state()
                                        gateway.client_id = req_client_id
                                        gateway.config = gateway.client_profile["config"]
                                        gateway.rules = gateway.client_profile["rules"]

                                        # クライアントIDが変更された場合、AICoreの会話フローを再読み込み
                                        if hasattr(gateway.ai_core, "set_client_id"):
                                            gateway.ai_core.set_client_id(req_client_id)
                                        elif hasattr(gateway.ai_core, "client_id"):
                                            gateway.ai_core.client_id = req_client_id
                                            if hasattr(gateway.ai_core, "reload_flow"):
                                                gateway.ai_core.reload_flow()

                                        # caller_numberをAICoreに設定
                                        if req_caller_number:
                                            gateway.ai_core.caller_number = req_caller_number
                                            self.logger.debug(
                                                "[Init] Set caller_number: %s",
                                                req_caller_number,
                                            )
                                        else:
                                            # caller_numberが送られてこない場合はNone（後で"-"として記録される）
                                            gateway.ai_core.caller_number = None
                                            self.logger.debug(
                                                "[Init] caller_number not provided in init message"
                                            )

                                        gateway._ensure_console_session(
                                            call_id_override=req_call_id
                                        )
                                        # 非同期タスクとして実行（結果を待たない）
                                        task = asyncio.create_task(
                                            gateway._queue_initial_audio_sequence(
                                                gateway.client_id
                                            )
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
                                            gateway.client_id,
                                        )

                                        self.logger.debug(
                                            "[Init] Loaded: %s",
                                            gateway.config.get("client_name"),
                                        )
                                    except Exception as e:
                                        self.logger.debug("[Init Error] %s", e)
                                    continue
                                if msg_type == "call_end":
                                    try:
                                        req_call_id = data.get("call_id")
                                        if req_call_id and gateway.call_id == req_call_id:
                                            gateway._stop_recording()
                                            gateway._complete_console_call()
                                    except Exception as e:
                                        self.logger.error(
                                            "call_end handling failed: %s", e
                                        )
                                    continue
                                # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

                            except json.JSONDecodeError:
                                pass
            except Exception:
                await asyncio.sleep(gateway.reconnect_delay)
            finally:
                gateway.websocket = None

    async def ws_server_loop(self) -> None:
        """WebSocketサーバーとしてAsterisk側からの接続を受け付ける"""
        gateway = self.manager.gateway
        ws_server_port = 9001
        ws_server_host = "0.0.0.0"

        # WebSocket起動前にポートを確認・解放
        self.logger.debug(
            "[BOOT] Checking WebSocket port %s availability", ws_server_port
        )
        gateway._free_port(ws_server_port)

        async def handle_asterisk_connection(websocket):
            """Asterisk側からのWebSocket接続を処理"""
            self.logger.info(
                "[WS Server] New connection from %s", websocket.remote_address
            )
            try:
                async for message in websocket:
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")

                            if msg_type == "init":
                                self.logger.info(
                                    "[WS Server] INIT from Asterisk: %s", data
                                )
                                # 既存のinit処理ロジックを再利用
                                await gateway._handle_init_from_asterisk(data)
                            else:
                                self.logger.debug(
                                    "[WS Server] Unknown message type: %s", msg_type
                                )
                        except json.JSONDecodeError as e:
                            self.logger.warning(
                                "[WS Server] Invalid JSON: %s", e
                            )
                        except Exception as e:
                            self.logger.error(
                                "[WS Server] Error processing message: %s",
                                e,
                                exc_info=True,
                            )
            except websockets.exceptions.ConnectionClosed:
                self.logger.debug(
                    "[WS Server] Connection closed: %s",
                    websocket.remote_address,
                )
            except Exception as e:
                self.logger.error(
                    "[WS Server] Connection error: %s", e, exc_info=True
                )

        while gateway.running:
            try:
                async with websockets.serve(
                    handle_asterisk_connection, ws_server_host, ws_server_port
                ) as server:
                    self.logger.info(
                        "[WS Server] Listening on ws://%s:%s",
                        ws_server_host,
                        ws_server_port,
                    )
                    # サーバーが実際に起動したことを確認
                    if server:
                        self.logger.info(
                            "[WS Server] Server started successfully, waiting for connections..."
                        )
                    # サーバーを起動し続ける
                    await asyncio.Future()  # 永久に待機
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    self.logger.error(
                        "[WS Server] Port %s still in use after cleanup, retrying in 5s...",
                        ws_server_port,
                    )
                    await asyncio.sleep(5)
                    # 再試行前に再度ポートを解放
                    gateway._free_port(ws_server_port)
                    continue
                else:
                    self.logger.error(
                        "[WS Server] Failed to start: %s", e, exc_info=True
                    )
                    await asyncio.sleep(5)  # エラー時は5秒待って再試行
            except Exception as e:
                self.logger.error(
                    "[WS Server] Failed to start: %s", e, exc_info=True
                )
                await asyncio.sleep(5)  # エラー時は5秒待って再試行
