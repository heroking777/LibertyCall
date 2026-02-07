#!/usr/bin/env python3
"""Network/server handling for realtime gateway."""
import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from gateway.common.network_ws_handler import NetworkWSHandler
from gateway.common.network_socket_server import NetworkSocketServer
from gateway.common.network_log_monitor import NetworkLogMonitor
from gateway.common.network_port_parser import NetworkPortParser


def _evt(msg: str) -> None:
    try:
        os.write(2, f"{time.time():.3f} [NET_EVT] {msg}\n".encode())
    except Exception:
        pass


class GatewayNetworkManager:
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        self.logger = gateway.logger
        self.ws_handler = NetworkWSHandler(self)
        self.socket_server = NetworkSocketServer(self)
        self.log_monitor = NetworkLogMonitor(self)
        self.port_parser = NetworkPortParser(self)

    def get_rtp_port_from_freeswitch(self) -> Optional[int]:
        return self.port_parser.get_rtp_port_from_freeswitch()

    def _setup_server_socket(self) -> None:
        self.socket_server.setup_server_socket()

    def _cleanup_sockets(self) -> None:
        self.socket_server.cleanup_sockets()

    async def _log_monitor_loop(self):
        await self.log_monitor.log_monitor_loop()

    async def _ws_client_loop(self):
        await self.ws_handler.ws_client_loop()

    async def _ws_server_loop(self):
        await self.ws_handler.ws_server_loop()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await self.socket_server.handle_client(reader, writer)

    async def _event_socket_server_loop(self) -> None:
        path = getattr(self.gateway, "event_socket_path", None)
        running = getattr(self.gateway, "running", None)
        _evt(
            f"_event_socket_server_loop ENTER path={path!r} pid={os.getpid()} running={running}"
        )
        self.logger.info("[NET_EVT_LOOP_ENTER] path=%s", path)
        try:
            _evt(
                f"_event_socket_server_loop CALL event_socket_server_loop path={path!r} gateway_event_server={getattr(self.gateway, 'event_server', None)}"
            )
            await self.socket_server.event_socket_server_loop()
            _evt(
                f"_event_socket_server_loop EXIT_OK path={path!r} gateway_event_server={getattr(self.gateway, 'event_server', None)}"
            )
        except BaseException as exc:
            _evt(
                f"_event_socket_server_loop LOOP_BASEEXC type={type(exc).__name__} repr={exc!r}\n"
                + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
            self.logger.exception("[NET_EVT_LOOP_FATAL]")
            raise
        finally:
            _evt(
                f"_event_socket_server_loop EXIT path={path!r} running={getattr(self.gateway, 'running', None)}"
            )
