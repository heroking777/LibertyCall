"""Playback start/stop control wrapper."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.audio.playback_manager import GatewayPlaybackManager


class PlaybackController:
    def __init__(self, manager: "GatewayPlaybackManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    async def handle_playback_start(self, call_id: str, audio_file: str) -> None:
        self.manager._handle_playback(call_id, audio_file)

    async def handle_playback_stop(self, call_id: str) -> None:
        self.manager._handle_playback(call_id, "")
