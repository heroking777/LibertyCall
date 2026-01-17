"""WebSocket client/server handling for network manager."""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import websockets

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.common.network_manager import GatewayNetworkManager


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
                                handled = await gateway.router.handle_control_message(data)
                                if handled:
                                    continue
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
                            handled = await gateway.router.handle_asterisk_message(data)
                            if not handled:
                                self.logger.debug(
                                    "[WS Server] Unknown message type: %s",
                                    data.get("type"),
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
