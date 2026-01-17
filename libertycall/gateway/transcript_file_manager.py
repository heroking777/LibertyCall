"""Transcript file/partial transcript management helpers."""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from .text_utils import normalize_text_for_comparison


class TranscriptFileManager:
    def __init__(self, core, logger: logging.Logger) -> None:
        self.core = core
        self.logger = logger

    def cleanup_stale_partials(self, max_age_sec: float = 30.0) -> None:
        self.core._cleanup_stale_partials(max_age_sec=max_age_sec)

    def ensure_partial_entry(self, call_id: str) -> None:
        if call_id not in self.core.partial_transcripts:
            self.core.partial_transcripts[call_id] = {"text": "", "updated": time.time()}

    def update_partial(self, call_id: str, text: str) -> None:
        prev_text = self.core.partial_transcripts[call_id].get("text", "")
        prev_text_normalized = prev_text.strip() if prev_text else ""
        text_normalized = text.strip() if text else ""

        if prev_text and not text.startswith(prev_text) and prev_text not in text:
            self.logger.warning(
                "[ASR_PARTIAL_NON_CUMULATIVE] call_id=%s prev=%r new=%r",
                call_id,
                prev_text,
                text,
            )

        prev_text_normalized_clean = normalize_text_for_comparison(prev_text_normalized)
        text_normalized_clean = normalize_text_for_comparison(text_normalized)

        if prev_text_normalized_clean != text_normalized_clean:
            self.core.partial_transcripts[call_id].pop("processed", None)

        self.core.partial_transcripts[call_id]["text_normalized"] = text_normalized
        self.core.partial_transcripts[call_id]["text"] = text
        self.core.partial_transcripts[call_id]["updated"] = time.time()

    def mark_partial_processed(self, call_id: str) -> None:
        self.core.partial_transcripts[call_id]["processed"] = True

    def is_partial_processed(self, call_id: str) -> bool:
        return bool(self.core.partial_transcripts[call_id].get("processed"))

    def get_partial_text(self, call_id: str) -> str:
        return self.core.partial_transcripts[call_id].get("text", "")

    def get_partial_normalized(self, call_id: str) -> str:
        return self.core.partial_transcripts[call_id].get("text_normalized", "")

    def pop_partial(self, call_id: str) -> str:
        partial_text = self.core.partial_transcripts[call_id].get("text", "")
        del self.core.partial_transcripts[call_id]
        return partial_text

    def should_process_partial(self, merged_text: str, is_greeting_detected: bool) -> bool:
        text_stripped = merged_text.strip() if merged_text else ""
        min_length_for_processing = 3 if is_greeting_detected else 5
        return bool(merged_text and len(text_stripped) >= min_length_for_processing)

    def greeting_detected(self, text_stripped: str) -> bool:
        greeting_keywords = ["もしもし", "もし", "おはよう", "こんにちは", "こんばんは", "失礼します"]
        return any(keyword in text_stripped for keyword in greeting_keywords)

    def should_skip_final(self, call_id: str, text: str) -> bool:
        text_normalized = normalize_text_for_comparison(text)
        partial_text_normalized = self.get_partial_normalized(call_id)
        if partial_text_normalized:
            partial_text_normalized = normalize_text_for_comparison(partial_text_normalized)
            if (
                partial_text_normalized == text_normalized
                and self.is_partial_processed(call_id)
            ):
                self.logger.info(
                    "[ASR_SKIP_FINAL] Already processed as partial: call_id=%s text=%r",
                    call_id,
                    text_normalized,
                )
                self.pop_partial(call_id)
                return True
        elif self.is_partial_processed(call_id):
            merged_text = self.get_partial_text(call_id)
            merged_text_normalized = normalize_text_for_comparison(merged_text)
            if merged_text_normalized == text_normalized:
                self.logger.info(
                    "[ASR_SKIP_FINAL] Already processed as partial: call_id=%s text=%r",
                    call_id,
                    text_normalized,
                )
                self.pop_partial(call_id)
                return True
        return False

    def merge_final(self, call_id: str, text: str) -> Tuple[str, str]:
        partial_text = ""
        if call_id in self.core.partial_transcripts:
            partial_text = self.get_partial_text(call_id)
            self.logger.debug(
                "[ASR_FINAL_MERGE] Merging partial=%r with final=%r",
                partial_text,
                text,
            )
            self.pop_partial(call_id)
        merged_text = text if text else partial_text
        return partial_text, merged_text

    def update_last_activity(self, call_id: str) -> None:
        self.core.last_activity[call_id] = time.time()

    def update_system_text_on_playback(self, call_id: str) -> None:
        try:
            playing = False
            if hasattr(self.core, "is_playing") and isinstance(self.core.is_playing, dict):
                playing = bool(self.core.is_playing.get(call_id, False))
            if not playing and getattr(self.core, "current_system_text", ""):
                self.core.current_system_text = ""
        except Exception:
            pass

    def ignore_system_echo(self, text: str) -> bool:
        try:
            if getattr(self.core, "current_system_text", ""):
                import re

                def _normalize(value: str) -> str:
                    if not value:
                        return ""
                    value = str(value)
                    value = re.sub(r"[。、！？\s]+", "", value)
                    return value

                sys_norm = _normalize(self.core.current_system_text)
                user_norm = _normalize(text)
                if sys_norm and user_norm and (user_norm in sys_norm or sys_norm in user_norm):
                    if len(user_norm) > 2:
                        self.logger.info(
                            "[ASR_FILTER] Ignored system echo: %r (matched system text)",
                            text,
                        )
                        return True
        except Exception:
            pass
        return False
