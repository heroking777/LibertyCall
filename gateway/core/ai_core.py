import logging
import subprocess

logger = logging.getLogger(__name__)
logger.error("!!! CRITICAL_LOAD: ai_core.py is LOADED from /opt/libertycall !!!")

import os
# 明示的に認証ファイルパスを指定（存在する候補ファイルがあればデフォルトで設定）
# 実稼働では環境変数で設定するのが望ましいが、ここでは一時的にデフォルトを補完する
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/opt/libertycall/config/google-credentials.json")
from typing import Optional, Tuple, List

from ..common.text_utils import normalize_text
from ..dialogue.flow_engine import FlowEngine
from .call_manager import (
    on_call_start as manage_call_start,
    on_call_end as manage_call_end,
    reset_call as manage_reset_call,
    trigger_transfer as manage_trigger_transfer,
    trigger_transfer_if_needed as manage_trigger_transfer_if_needed,
    schedule_auto_hangup as manage_schedule_auto_hangup,
)
from ..dialogue.dialogue_engine import (
    generate_reply,
    run_conversation_flow,
    handle_entry_phase,
    handle_qa_phase,
    handle_after_085_phase,
    handle_entry_confirm_phase,
    handle_waiting_phase,
    handle_not_heard_phase,
    handle_flow_engine_transition,
    handle_closing_phase,
    handle_handoff_phase,
    handle_handoff_confirm,
)
from ..dialogue.dialogue_handler import process_dialogue as handle_process_dialogue, on_asr_error
from ..dialogue.prompt_factory import render_templates_from_ids, render_templates
from ..dialogue.intent_classifier import classify_simple_intent, is_hallucination
from ..dialogue.flow_manager import reload_flow as reload_flow_manager
from ..asr.asr_logic import (
    load_phrase_hints,
    enable_asr as enable_asr_logic,
    cleanup_stale_partials,
    check_for_transcript as check_for_transcript_logic,
)
from ..audio.audio_orchestrator import (
    break_playback,
    play_audio_response,
    play_template_sequence,
    send_playback_request_http,
)
from ..common.activity_monitor import start_activity_monitor
from ..asr.asr_manager import on_new_audio as handle_new_audio, init_asr
from .config_loader import load_flow, load_json, load_keywords_from_config
from .core_initializer import init_core_state
from ..audio.audio_manager import (
    synthesize_text,
    synthesize_template_audio_for_core,
    synthesize_template_sequence_for_core,
)
from .state_logic import ConversationState, MisunderstandingGuard, HandoffStateMachine
from ..transcript.transcript_handler import handle_transcript
from .session_utils import (
    save_session_summary_from_core,
    save_debug_wav,
    save_transcript_event_from_core,
    append_call_log_entry,
)
from .resource_manager import cleanup_call, cleanup_asr_instance
from .state_store import get_session_state, reset_session_state, set_call_id

FS_CLI_PATH = os.getenv("FS_CLI_PATH", "/usr/local/freeswitch/bin/fs_cli")

MIN_TEXT_LENGTH_FOR_INTENT = 2  # 「はい」「うん」も判定可能に
class AICore:
    # キーワードはインスタンス変数として初期化時にJSONから読み込まれる（後方互換性のためクラス変数としても定義）
    AFTER_085_NEGATIVE_KEYWORDS = []  # 初期化時にJSONから読み込まれる
    ENTRY_TRIGGER_KEYWORDS = []  # 初期化時にJSONから読み込まれる
    CLOSING_YES_KEYWORDS = []  # 初期化時にJSONから読み込まれる
    CLOSING_NO_KEYWORDS = []  # 初期化時にJSONから読み込まれる

    def __init__(self, init_clients: bool = True, client_id: str = "000"):
        self.logger = logging.getLogger(__name__)
        self._handoff_sm = HandoffStateMachine(self.logger)
        self._mis_guard = MisunderstandingGuard(self.logger)
        self.history: List[List[str]] = []
        self.init_clients = init_clients
        self.client_id = client_id
        init_core_state(self, client_id)
        if not init_clients:
            self.flow_engine = None
            self.flow_engines = {}
        
        init_asr(self)
    
    def set_call_id(self, call_id: str):
        set_call_id(self, call_id)
    
    def enable_asr(self, uuid: str, client_id: Optional[str] = None) -> None:
        enable_asr_logic(self, uuid, client_id=client_id)
    
    def handle_flow_engine_transition(
        self,
        call_id: str,
        text: str,
        normalized_text: str,
        intent: str,
        state: ConversationState,
        flow_engine: FlowEngine,
        client_id: str,
    ) -> Tuple[str, List[str], str, bool]:
        return handle_flow_engine_transition(
            self,
            call_id,
            text,
            normalized_text,
            intent,
            state,
            flow_engine,
            client_id,
        )
    
    def play_template_sequence(self, call_id: str, template_ids: List[str], client_id: Optional[str] = None) -> None:
        play_template_sequence(self, call_id, template_ids, client_id=client_id)
    
    def send_playback_request_http(self, call_id: str, audio_file: str) -> None:
        send_playback_request_http(call_id, audio_file)
    
    def save_debug_wav(self, pcm16k_bytes: bytes):
        save_debug_wav(pcm16k_bytes)
    

    def is_hallucination(self, text):
        return is_hallucination(text)

    def on_call_end(self, call_id: Optional[str], source: str = "unknown") -> None:
        manage_call_end(call_id, source=source)

    def cleanup_asr_instance(self, call_id: str) -> None:
        cleanup_asr_instance(self, call_id)

    def cleanup_call(self, call_id: str) -> None:
        cleanup_call(self, call_id)

    def load_flow(self, client_id: str) -> dict:
        return load_flow(self, client_id)
    
    def load_json(self, path: str, default: str = None) -> dict:
        return load_json(self, path, default=default)
    
    def load_keywords_from_config(self) -> None:
        load_keywords_from_config(self)

    # --- legacy compatibility helpers (keep tests relying on old private API alive) ---
    def _load_flow(self, client_id: str) -> dict:
        return self.load_flow(client_id)

    def _load_json(self, path: str, default: str | None = None) -> dict:
        return self.load_json(path, default=default)

    def _load_keywords_from_config(self) -> None:
        self.load_keywords_from_config()

    def _log_ai_templates(self, template_ids: List[str]) -> None:
        self.history.append(list(template_ids or []))

    def _append_call_log(self, role: str, text: str, template_id: Optional[str] = None) -> None:
        append_call_log_entry(self, role, text, template_id=template_id)

    def start_activity_monitor(self) -> None:
        start_activity_monitor(self)

    def _start_activity_monitor(self) -> None:
        self.start_activity_monitor()

    def _load_phrase_hints(self):
        return getattr(self, "_phrase_hints", [])

    def _init_tts(self):
        if hasattr(self, "init_tts"):
            return self.init_tts()
        return None

    def _get_session_state(self, call_id: str):
        return get_session_state(self, call_id)

    def _reset_session_state(self, call_id: str) -> None:
        reset_session_state(self, call_id)

    def _save_transcript_event(
        self, call_id: str, text: str, is_final: bool, kwargs: dict
    ) -> None:
        self.save_transcript_event(call_id, text, is_final, kwargs)

    def _trigger_transfer_if_needed(self, call_id: str, state: ConversationState) -> None:
        self.trigger_transfer_if_needed(call_id, state)

    def _handle_flow_engine_transition(
        self,
        call_id: str,
        text: str,
        normalized_text: str,
        intent: str,
        state: ConversationState,
        flow_engine: FlowEngine,
        client_id: str,
    ) -> Tuple[str, List[str], str, bool]:
        return self.handle_flow_engine_transition(
            call_id,
            text,
            normalized_text,
            intent,
            state,
            flow_engine,
            client_id,
        )

    def _play_template_sequence(
        self,
        call_id: str,
        template_ids: List[str],
        client_id: Optional[str] = None,
    ) -> None:
        self.play_template_sequence(call_id, template_ids, client_id=client_id)

    def _schedule_auto_hangup(self, call_id: str, delay_sec: float = 60.0) -> None:
        self.schedule_auto_hangup(call_id, delay_sec=delay_sec)

    def _is_hallucination(self, text: str) -> bool:
        return self.is_hallucination(text)

    def _generate_reply(
        self, call_id: str, raw_text: str
    ) -> Tuple[str, List[str], str, bool]:
        return self.generate_reply(call_id, raw_text)

        
    def save_transcript_event(self, call_id: str, text: str, is_final: bool, kwargs: dict) -> None:
        save_transcript_event_from_core(self, call_id, text, is_final, kwargs)
    
    def save_session_summary(self, call_id: str) -> None:
        save_session_summary_from_core(self, call_id)
    
    def reload_flow(self) -> None:
        reload_flow_manager(self)
    
    def set_client_id(self, client_id: str) -> None:
        """
        クライアントIDを変更して会話フローを再読み込みする
        
        :param client_id: 新しいクライアントID
        """
        self.client_id = client_id
        reload_flow_manager(self)

    def synthesize_text_with_gemini(self, text: str, speaking_rate: float = 1.0, pitch: float = 0.0) -> Optional[bytes]:
        return synthesize_text(text, speaking_rate, pitch)

    def synthesize_template_audio(self, template_id: str) -> Optional[bytes]:
        return synthesize_template_audio_for_core(self, template_id)

    def synthesize_template_sequence(self, template_ids: List[str]) -> Optional[bytes]:
        return synthesize_template_sequence_for_core(self, template_ids)

    def trigger_transfer(self, call_id: str) -> None:
        manage_trigger_transfer(self, call_id)

    def trigger_transfer_if_needed(self, call_id: str, state: ConversationState) -> None:
        manage_trigger_transfer_if_needed(self, call_id, state)

    def schedule_auto_hangup(self, call_id: str, delay_sec: float = 60.0) -> None:
        manage_schedule_auto_hangup(self, call_id, delay_sec=delay_sec)

    def on_call_start(self, call_id: str, client_id: str = None, **kwargs) -> None:
        manage_call_start(self, call_id, client_id=client_id, **kwargs)

    def handle_entry_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_entry_phase(self, call_id, raw_text, normalized_text, state)

    def handle_qa_phase(
        self,
        call_id: str,
        raw_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_qa_phase(self, call_id, raw_text, state)

    def handle_after_085_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_after_085_phase(self, call_id, raw_text, normalized_text, state)

    def handle_entry_confirm_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_entry_confirm_phase(self, call_id, raw_text, normalized_text, state)
    
    def handle_waiting_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_waiting_phase(self, call_id, raw_text, normalized_text, state)
    
    def handle_not_heard_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_not_heard_phase(self, call_id, raw_text, normalized_text, state)

    def handle_closing_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_closing_phase(self, call_id, raw_text, normalized_text, state)

    def handle_handoff_confirm(
        self,
        call_id: str,
        raw_text: str,
        intent: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], str, bool]:
        return handle_handoff_confirm(self, call_id, raw_text, intent, state)

    def handle_handoff_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_handoff_phase(self, call_id, raw_text, normalized_text, state)

    def run_conversation_flow(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[List[str], str, bool]:
        return run_conversation_flow(self, call_id, raw_text)

    def generate_reply(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[str, List[str], str, bool]:
        return generate_reply(self, call_id, raw_text)

    def process_dialogue(self, pcm16k_bytes):
        return handle_process_dialogue(self, pcm16k_bytes)

    def on_new_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        handle_new_audio(self, call_id, pcm16k_bytes)

    def _on_asr_error(self, call_id: str, error: Exception) -> None:
        on_asr_error(self, call_id, error)

    def _send_fallback_tone(self, call_id: str) -> None:
        if not call_id:
            return
        tone_cmd = f"uuid_broadcast {call_id} tone_stream://%(1000,0,660) aleg"
        try:
            subprocess.run(
                [FS_CLI_PATH, "-x", tone_cmd],
                check=False,
                capture_output=True,
                text=True,
            )
            self.logger.warning("[AICORE] Fallback tone triggered: call_id=%s", call_id)
        except Exception:
            self.logger.exception("[AICORE] Failed to trigger fallback tone: call_id=%s", call_id)

    def on_transcript(self, *args, **kwargs) -> Optional[str]:
        """ASR認識結果を受信（Phase2-3暫定実装）"""

        transcript = kwargs.pop("transcript", None)
        call_id = kwargs.pop("call_id", None)
        confidence = float(kwargs.pop("confidence", 1.0))
        is_final_kw = kwargs.pop("is_final", None)

        if args:
            # 旧シグネチャ互換: (call_id, text, is_final)
            if call_id is None:
                call_id = args[0]
            if len(args) > 1 and transcript is None:
                transcript = args[1]
            if len(args) > 2 and is_final_kw is None:
                is_final_kw = args[2]

        if transcript is None:
            transcript = kwargs.pop("text", "")

        if call_id is None:
            call_id = kwargs.get("uuid") or "unknown"

        is_final = True if is_final_kw is None else bool(is_final_kw)
        transcript = transcript or ""

        self.logger.info(
            "📝 AICore received: '%s' (final=%s, conf=%.2f, call=%s)",
            transcript,
            is_final,
            confidence,
            call_id,
        )

        if is_final and confidence >= 0.6:
            self.logger.info("🤖 [TODO Phase3] Generate AI response for: '%s'", transcript)
        else:
            reason = "interim result" if not is_final else f"low confidence ({confidence:.2f})"
            self.logger.debug("🔄 Skipping AI response: %s", reason)

        try:
            return handle_transcript(self, call_id, transcript, is_final=is_final, **kwargs)
        except Exception as exc:
            self.logger.exception("[AICORE] on_transcript error: call_id=%s", call_id)
            self._send_fallback_tone(call_id)
            return None
    
    def _cleanup_stale_partials(self, max_age_sec: float = 30.0) -> None:
        cleanup_stale_partials(self, max_age_sec=max_age_sec)
    
    def check_for_transcript(self, call_id: str) -> Optional[Tuple[str, float, float, float]]:
        return check_for_transcript_logic(self, call_id)

    def reset_call(self, call_id: str) -> None:
        manage_reset_call(self, call_id)