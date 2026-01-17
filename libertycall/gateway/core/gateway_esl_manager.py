"""ESL connection handling for the gateway."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


class GatewayESLManager:
    def __init__(self, gateway: "RealtimeGateway") -> None:
        self.gateway = gateway
        self.logger = gateway.logger

    def _init_esl_connection(self) -> None:
        """FreeSWITCH Event Socket Interface (ESL) に接続"""
        try:
            from libs.esl.ESL import ESLconnection

            esl_host = os.getenv("LC_FREESWITCH_ESL_HOST", "127.0.0.1")
            esl_port = os.getenv("LC_FREESWITCH_ESL_PORT", "8021")
            esl_password = os.getenv("LC_FREESWITCH_ESL_PASSWORD", "ClueCon")

            self.logger.info(
                "[ESL] Connecting to FreeSWITCH ESL: %s:%s", esl_host, esl_port
            )
            self.gateway.esl_connection = ESLconnection(
                esl_host, esl_port, esl_password
            )

            if not self.gateway.esl_connection.connected():
                self.logger.error("[ESL] Failed to connect to FreeSWITCH ESL")
                self.gateway.esl_connection = None
                return

            self.logger.info("[ESL] Connected to FreeSWITCH ESL successfully")
        except ImportError:
            self.logger.warning(
                "[ESL] ESL module not available, playback interruption will be disabled"
            )
            self.gateway.esl_connection = None
        except Exception as e:
            self.logger.exception("[ESL] Failed to initialize ESL connection: %s", e)
            self.gateway.esl_connection = None
