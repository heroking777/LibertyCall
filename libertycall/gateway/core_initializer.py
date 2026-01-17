"""Initialization helpers for AICore state."""

from __future__ import annotations

import threading
from typing import Any, Dict

from .flow_engine import FlowEngine


def init_core_state(core, client_id: str) -> None:
    core.flow = core._load_flow(client_id)
    core.templates = core._load_json(
        f"/opt/libertycall/config/clients/{client_id}/templates.json",
        default="/opt/libertycall/config/system/default_templates.json",
    )
    core.keywords = core._load_json(
        f"/opt/libertycall/config/clients/{client_id}/keywords.json",
        default="/opt/libertycall/config/system/default_keywords.json",
    )

    core.flow_engine = FlowEngine(client_id=client_id)
    core.flow_engines: Dict[str, FlowEngine] = {}
    core.call_client_map: Dict[str, str] = {}
    core.is_playing: Dict[str, bool] = {}
    core.last_activity: Dict[str, float] = {}
    core.last_template_play: Dict[str, Dict[str, float]] = {}
    core.session_info: Dict[str, Dict[str, Any]] = {}

    core.esl_connection = None
    core._activity_monitor_thread = None
    core._activity_monitor_running = False
    core._start_activity_monitor()

    core.logger.info("FlowEngine initialized for default client: %s", client_id)

    core._load_keywords_from_config()
    core.call_id = None
    core.caller_number = None
    core.log_session_id = None
    core.session_states: Dict[str, Dict[str, Any]] = {}
    core.partial_transcripts: Dict[str, Dict[str, Any]] = {}
    core.debug_save_wav = False
    core.call_id = None
    core._wav_saved = False
    core._wav_chunk_counter = 0
    core.asr_model = None
    core.transfer_callback = None
    core.hangup_callback = None
    core.playback_callback = None
    core._auto_hangup_timers: Dict[str, threading.Timer] = {}
    core._call_started_calls: set[str] = set()
    core._intro_played_calls: set[str] = set()
    core.last_start_times: Dict[str, float] = {}
    core.current_system_text = ""
    core.TEMPLATE_TEXTS = {
        "000": "この電話は応対品質の向上と正確なご案内のため録音させていただいております",
        "004": "お電話ありがとうございます",
        "006_SYS": "ただいま電話に出ることができません",
        "081": "もしもし、聞こえていますでしょうか",
        "110": "発信音の後にメッセージを入れてください",
    }

    core.logger.info(
        "AI_CORE_VERSION: version=2025-12-01-auto-hangup hangup_callback=%s",
        "set" if core.hangup_callback else "none",
    )
