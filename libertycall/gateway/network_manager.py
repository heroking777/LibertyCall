#!/usr/bin/env python3
"""Network/server handling for realtime gateway."""
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from libertycall.gateway.network_ws_handler import NetworkWSHandler
from libertycall.gateway.network_socket_server import NetworkSocketServer
from libertycall.gateway.network_log_monitor import NetworkLogMonitor
from libertycall.gateway.network_port_parser import NetworkPortParser


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
        await self.socket_server.event_socket_server_loop()
