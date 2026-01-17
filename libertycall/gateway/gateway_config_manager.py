"""Gateway configuration loading and environment defaults."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


class GatewayConfigManager:
    def __init__(self, logger) -> None:
        self.logger = logger

    def resolve_rtp_port(
        self, config: Dict[str, Any], rtp_port_override: int | None = None
    ) -> int:
        """Resolve RTP port from CLI/env/config."""
        if rtp_port_override is not None:
            self.logger.info(
                "[INIT] RTP port overridden by CLI argument: %s", rtp_port_override
            )
            return rtp_port_override

        env_port = os.getenv("LC_RTP_PORT") or os.getenv("LC_GATEWAY_PORT")
        if env_port:
            try:
                port = int(env_port)
                env_name = "LC_RTP_PORT" if os.getenv("LC_RTP_PORT") else "LC_GATEWAY_PORT"
                self.logger.debug("%s override detected: %s", env_name, port)
                return port
            except ValueError:
                self.logger.warning(
                    "LC_RTP_PORT/LC_GATEWAY_PORT is invalid (%s). Falling back to config file.",
                    env_port,
                )

        return config["rtp"].get("listen_port", 7100)

    @staticmethod
    def load_config(config_path: Path) -> Dict[str, Any]:
        try:
            with open(config_path, "r", encoding="utf-8") as file_obj:
                return yaml.safe_load(file_obj)
        except FileNotFoundError:
            return {
                "rtp": {
                    "listen_host": "0.0.0.0",
                    "listen_port": 7002,
                    "payload_type": 0,
                    "sample_rate": 8000,
                },
                "ws": {"url": "ws://localhost:8000/ws", "reconnect_delay_sec": 5},
            }

    @staticmethod
    def setup_environment() -> None:
        os.environ.setdefault(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/opt/libertycall/config/google-credentials.json",
        )
