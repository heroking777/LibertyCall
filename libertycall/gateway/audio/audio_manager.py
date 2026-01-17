"""Audio helpers ranging from initial prompts to Gemini synthesis."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from ..common.text_utils import get_template_config
from .tts_utils import (
    synthesize_text_with_gemini,
    synthesize_template_audio,
    synthesize_template_sequence,
)

LOGGER = logging.getLogger(__name__)


class AudioManager:
    """Load and resolve client audio assets for playback."""

    def __init__(self, project_root: Path | str, logger: Optional[logging.Logger] = None) -> None:
        self.project_root = Path(project_root)
        self.clients_dir = self.project_root / "clients"
        self.logger = logger or LOGGER

    def play_incoming_sequence(self, client_id: Optional[str]) -> List[Path]:
        """Return the configured greeting sequence as absolute Paths."""

        if not client_id:
            self.logger.warning("[AUDIO_MANAGER] client_id is missing; skipping initial sequence")
            return []

        sequence_ids = self._load_sequence_ids(client_id)
        audio_paths: List[Path] = []

        for audio_id in sequence_ids:
            audio_path = self._resolve_audio_path(client_id, audio_id)
            if audio_path:
                audio_paths.append(audio_path)

        if not audio_paths:
            self.logger.warning(
                "[AUDIO_MANAGER] No playable audio files found for client_id=%s sequence=%s",
                client_id,
                sequence_ids,
            )

        return audio_paths

    def _load_sequence_ids(self, client_id: str) -> List[str]:
        config_path = self.clients_dir / client_id / "config" / "incoming_sequence.json"
        try:
            with open(config_path, "r", encoding="utf-8") as fp:
                config = json.load(fp)
        except FileNotFoundError:
            self.logger.error(
                "[AUDIO_MANAGER] incoming_sequence.json not found for client_id=%s path=%s",
                client_id,
                config_path,
            )
            return []
        except json.JSONDecodeError as exc:
            self.logger.error(
                "[AUDIO_MANAGER] Failed to parse %s: %s",
                config_path,
                exc,
            )
            return []

        sequence = config.get("incoming_sequence", [])
        if not isinstance(sequence, list):
            self.logger.error(
                "[AUDIO_MANAGER] incoming_sequence must be a list (client_id=%s)",
                client_id,
            )
            return []
        return [str(audio_id) for audio_id in sequence]

    def _resolve_audio_path(self, client_id: str, audio_id: str) -> Optional[Path]:
        audio_dir = self.clients_dir / client_id / "audio"
        candidates = [
            audio_dir / f"{audio_id}.wav",
            audio_dir / f"{audio_id}_8k.wav",
            audio_dir / f"{audio_id}_8k_norm.wav",
        ]

        for path in candidates:
            if path.exists():
                return path

        self.logger.warning(
            "[AUDIO_MANAGER] Missing audio asset for client_id=%s audio_id=%s candidates=%s",
            client_id,
            audio_id,
            [str(p) for p in candidates],
        )
        return None


def synthesize_text(core, text: str, speaking_rate: float = 1.0, pitch: float = 0.0) -> Optional[bytes]:
    if not core.use_gemini_tts:
        return None
    return synthesize_text_with_gemini(text, speaking_rate, pitch)


def synthesize_template_audio_for_core(core, template_id: str) -> Optional[bytes]:
    if not core.use_gemini_tts:
        return None

    def get_template_config_with_client(template_id: str):
        if core.templates and template_id in core.templates:
            return core.templates[template_id]
        return get_template_config(template_id)

    return synthesize_template_audio(template_id, get_template_config_with_client)


def synthesize_template_sequence_for_core(core, template_ids: List[str]) -> Optional[bytes]:
    if not template_ids:
        return None

    if not core.use_gemini_tts:
        return None

    def get_template_config_with_client(template_id: str):
        if core.templates and template_id in core.templates:
            return core.templates[template_id]
        return get_template_config(template_id)

    return synthesize_template_sequence(template_ids, get_template_config_with_client)


__all__ = [
    "AudioManager",
    "synthesize_text",
    "synthesize_template_audio_for_core",
    "synthesize_template_sequence_for_core",
]
