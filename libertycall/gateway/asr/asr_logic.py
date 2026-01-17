"""ASR control helpers extracted from AICore."""

from __future__ import annotations

import logging
import os
import time
from typing import List, Optional, Tuple

from ..dialogue.flow_engine import FlowEngine
from ..core.state_store import get_session_state


def load_phrase_hints(core) -> List[str]:
    try:
        from libertycall.config.config import ASR_PHRASE_HINTS  # type: ignore[import-untyped]

        if ASR_PHRASE_HINTS:
            core.logger.info("AICore: phrase_hints を読み込みました: %s", ASR_PHRASE_HINTS)
            return ASR_PHRASE_HINTS
    except (ImportError, AttributeError):
        pass

    env_phrase_hints = os.getenv("LC_ASR_PHRASE_HINTS")
    if env_phrase_hints:
        hints = [h.strip() for h in env_phrase_hints.split(",") if h.strip()]
        if hints:
            core.logger.info("AICore: phrase_hints を環境変数から読み込みました: %s", hints)
            return hints

    return []


def enable_asr(core, uuid: str, client_id: Optional[str] = None) -> None:
    if not core.asr_model:
        core.logger.warning("enable_asr: ASR model not initialized (uuid=%s)", uuid)
        return

    if not core.streaming_enabled:
        core.logger.warning("enable_asr: streaming not enabled (uuid=%s)", uuid)
        return

    if not client_id:
        client_id = core.call_client_map.get(uuid) or core.client_id or "000"

    core.call_client_map[uuid] = client_id

    if uuid not in core.flow_engines:
        try:
            core.flow_engines[uuid] = FlowEngine(client_id=client_id)
            core.logger.info("FlowEngine created for call: uuid=%s client_id=%s", uuid, client_id)
        except Exception as exc:
            core.logger.error(
                "Failed to create FlowEngine for uuid=%s client_id=%s: %s",
                uuid,
                client_id,
                exc,
            )
            core.flow_engines[uuid] = core.flow_engine

    state = get_session_state(core, uuid)
    if state.phase == "ENTRY" or not state.phase:
        state.phase = "ENTRY"
        state.meta["client_id"] = client_id
        core.logger.info("Session state initialized: uuid=%s phase=ENTRY client_id=%s", uuid, client_id)

    core.set_call_id(uuid)

    if hasattr(core.asr_model, "_start_stream_worker"):
        core.asr_model._start_stream_worker(uuid)
        core.logger.info("ASR enabled for call uuid=%s client_id=%s", uuid, client_id)
        runtime_logger = logging.getLogger("runtime")
        runtime_logger.info("[ASR] start uuid=%s client_id=%s", uuid, client_id)
    else:
        core.logger.error("enable_asr: ASR model does not have _start_stream_worker method (uuid=%s)", uuid)


def cleanup_stale_partials(core, max_age_sec: float = 30.0) -> None:
    now = time.time()
    stale_keys = [
        call_id
        for call_id, data in core.partial_transcripts.items()
        if now - data.get("updated", 0) > max_age_sec
    ]
    for key in stale_keys:
        core.logger.warning(
            "PARTIAL_CLEANUP: removing stale partial for call_id=%s (age=%.1fs)",
            key,
            now - core.partial_transcripts[key].get("updated", 0),
        )
        del core.partial_transcripts[key]


def check_for_transcript(core, call_id: str) -> Optional[Tuple[str, float, float, float]]:
    if not core.streaming_enabled:
        return None

    if core.asr_model is None:
        return None

    try:
        result = core.asr_model.poll_result(call_id)  # type: ignore[union-attr]
    except AttributeError:
        return None

    if result is None:
        return None

    return result
