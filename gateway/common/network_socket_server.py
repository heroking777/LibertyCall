"""TCP/Unix socket server handling for network manager."""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.common.network_manager import GatewayNetworkManager


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
                    response = await gateway.router.handle_event_socket_message(
                        message
                    )
                    writer.write(
                        (json.dumps(response) + "\n").encode("utf-8")
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
