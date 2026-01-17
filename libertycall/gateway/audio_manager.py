"""Audio synthesis helpers extracted from AICore."""

from __future__ import annotations

from typing import List, Optional

from .text_utils import get_template_config
from .tts_utils import (
    synthesize_text_with_gemini,
    synthesize_template_audio,
    synthesize_template_sequence,
)


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
