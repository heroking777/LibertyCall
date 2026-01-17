"""Legacy shim exposing AudioManager from the new audio package."""

from __future__ import annotations

from libertycall.gateway.audio import AudioManager

__all__ = ["AudioManager"]
