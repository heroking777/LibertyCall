import logging

logger = logging.getLogger(__name__)
logger.error("!!! CRITICAL_LOAD: ai_core.py is LOADED from /opt/libertycall !!!")

import os
# 明示的に認証ファイルパスを指定（存在する候補ファイルがあればデフォルトで設定）
# 実稼働では環境変数で設定するのが望ましいが、ここでは一時的にデフォルトを補完する
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/opt/libertycall/config/google-credentials.json")
import time
import threading
from typing import Optional, Tuple, List, Dict, Any, Callable

from .text_utils import get_template_config, normalize_text
from .flow_engine import FlowEngine
from .api_client import init_api_clients
from .call_manager import (
    on_call_start as manage_call_start,
    on_call_end as manage_call_end,
    reset_call as manage_reset_call,
    trigger_transfer as manage_trigger_transfer,
    trigger_transfer_if_needed as manage_trigger_transfer_if_needed,
    schedule_auto_hangup as manage_schedule_auto_hangup,
)
from .dialogue_engine import (
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
from .prompt_factory import render_templates_from_ids, render_templates
from .audio_orchestrator import (
    break_playback,
    play_audio_response,
    play_template_sequence,
    send_playback_request_http,
)
from .activity_monitor import start_activity_monitor
from .asr_manager import on_new_audio as handle_new_audio
from .config_loader import load_flow, load_json, load_keywords_from_config
from .core_initializer import init_core_state
from .tts_utils import (
    synthesize_text_with_gemini,
    synthesize_template_audio,
    synthesize_template_sequence,
)
from .google_asr import GoogleASR
from .state_logic import ConversationState, MisunderstandingGuard, HandoffStateMachine
from .transcript_handler import handle_transcript
from .session_utils import (
    get_session_dir,
    ensure_session_dir,
    save_session_summary_from_core,
    append_call_log_entry,
    log_ai_templates,
    save_debug_wav,
    save_transcript_event_from_core,
    cleanup_stale_sessions,
)
from .resource_manager import cleanup_call, cleanup_asr_instance
from .state_store import get_session_state, reset_session_state

# 定数定義
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
        self.init_clients = init_clients
        self.client_id = client_id
        init_core_state(self, client_id)
        
        # ASR プロバイダの選択（デフォルト: google）
        asr_provider = os.getenv("LC_ASR_PROVIDER", "google").lower()
        
        # プロバイダの検証（local を含む不正な値はエラー）
        if asr_provider not in ["google", "whisper"]:
            raise ValueError(
                f"未知のASRプロバイダ: {asr_provider}\n"
                f"有効な値: 'google' または 'whisper'\n"
                f"（'local' はサポートされていません。'whisper' を使用してください。）"
            )
        
        self.asr_provider = asr_provider  # プロバイダを属性として保持
        self.logger.info(f"AICore: ASR provider = {asr_provider}")
        
        # ストリーミングモード判定
        self.streaming_enabled = os.getenv("LC_ASR_STREAMING_ENABLED", "0") == "1"
        
        if self.init_clients:
            # ASR モデルの初期化（プロバイダごとに完全に分離）
            if asr_provider == "google":
                # phrase_hints の読み込み
                phrase_hints = self._load_phrase_hints()
                
                try:
                    self.asr_model = GoogleASR(
                        language_code="ja",  # universal_speech_modelは"ja"をサポート（"ja-JP"は無効）
                        sample_rate=16000,  # Gateway側で既に16kHzに変換済み
                        phrase_hints=phrase_hints,
                        ai_core=self,  # AICore への参照を渡す（on_transcript 呼び出し用）
                        error_callback=self._on_asr_error,  # ASR エラー時のコールバック
                    )
                    self.logger.info("AICore: GoogleASR を初期化しました")
                    # 【追加】通話ごとの独立したASRインスタンス管理用辞書
                    self.asr_instances: Dict[str, GoogleASR] = {}
                    self.asr_lock = threading.Lock()  # ASRインスタンス作成用ロック（競合状態防止）
                    self._phrase_hints = phrase_hints  # 新規インスタンス作成時に使用
                    print("[AICORE_INIT] asr_instances initialized with lock", flush=True)
                except Exception as e:
                    error_msg = str(e)
                    if "was not found" in error_msg or "credentials" in error_msg.lower():
                        self.logger.error(
                            f"AICore: GoogleASR の初期化に失敗しました（認証エラー）: {error_msg}\n"
                            f"環境変数 LC_GOOGLE_PROJECT_ID と LC_GOOGLE_CREDENTIALS_PATH を確認してください。\n"
                            f"ASR機能は無効化されますが、GatewayはRTP受信を継続します。"
                        )
                    else:
                        self.logger.error(f"AICore: GoogleASR の初期化に失敗しました: {error_msg}\nASR機能は無効化されますが、GatewayはRTP受信を継続します。")
                    # エラーを再スローせず、asr_modelをNoneに設定して続行
                    self.asr_model = None
                    self.logger.warning("AICore: ASR機能なしでGatewayを起動します（RTP受信は継続されます）")
            elif asr_provider == "whisper":
                # WhisperLocalASR は whisper プロバイダ使用時のみインポート（google 使用時は絶対にインポートしない）
                from libertycall.asr.whisper_local import WhisperLocalASR  # type: ignore[import-untyped]
                
                self.logger.debug("AICore: Loading Whisper via WhisperLocalASR...")
                # WhisperLocalASR を使用（16kHz入力想定）
                self.asr_model = WhisperLocalASR(
                    model_name="base",
                    input_sample_rate=16000,  # Gateway側で既に16kHzに変換済み
                    language="ja",
                    device="cpu",
                    compute_type="int8",
                    temperature=0.0,
                    vad_filter=False,
                    vad_parameters=None
                )
                self.logger.info("AICore: WhisperLocalASR を初期化しました")
            
            if self.streaming_enabled:
                self.logger.info("AICore: ストリーミングASRモード有効")
            
            # TTS の初期化
            self._init_tts()
            
            # 起動時ログ（ASR_BOOT）を強制的に出力
            self.logger.info(f"ASR_BOOT: provider={asr_provider} streaming_enabled={self.streaming_enabled}")
        else:
            self.logger.info("AICore: init_clients=False のため ASR/TTS 初期化をスキップします (simulation mode)")
    
    def _load_phrase_hints(self) -> List[str]:
        """
        phrase_hints を設定ファイルから読み込む
        
        :return: phrase_hints のリスト
        """
        try:
            from libertycall.config.config import ASR_PHRASE_HINTS  # type: ignore[import-untyped]
            if ASR_PHRASE_HINTS:
                self.logger.info(f"AICore: phrase_hints を読み込みました: {ASR_PHRASE_HINTS}")
                return ASR_PHRASE_HINTS
        except (ImportError, AttributeError):
            pass
        
        # 環境変数から読み込む（カンマ区切り）
        env_phrase_hints = os.getenv("LC_ASR_PHRASE_HINTS")
        if env_phrase_hints:
            hints = [h.strip() for h in env_phrase_hints.split(",") if h.strip()]
            if hints:
                self.logger.info(f"AICore: phrase_hints を環境変数から読み込みました: {hints}")
                return hints
        
        return []
    
    def _init_tts(self):
        init_api_clients(self)
    
    def set_call_id(self, call_id: str):
        """call_idを設定し、WAV保存フラグをリセット"""
        self.call_id = call_id
        self._wav_saved = False
        self._wav_chunk_counter = 0
    
    def enable_asr(self, uuid: str, client_id: Optional[str] = None) -> None:
        """
        FreeSWITCHからの通知を受けてASRストリーミングを開始する
        
        :param uuid: 通話UUID（FreeSWITCHのcall UUID）
        :param client_id: クライアントID（指定されない場合はデフォルトまたは自動判定）
        """
        if not self.asr_model:
            self.logger.warning(f"enable_asr: ASR model not initialized (uuid={uuid})")
            return
        
        if not self.streaming_enabled:
            self.logger.warning(f"enable_asr: streaming not enabled (uuid={uuid})")
            return
        
        # クライアントIDの決定（優先順位: 引数 > 既存のマッピング > デフォルト）
        if not client_id:
            client_id = self.call_client_map.get(uuid) or self.client_id or "000"
        
        # call_idとclient_idのマッピングを保存
        self.call_client_map[uuid] = client_id
        
        # このUUID用のFlowEngineが存在しない場合は作成
        if uuid not in self.flow_engines:
            try:
                self.flow_engines[uuid] = FlowEngine(client_id=client_id)
                self.logger.info(f"FlowEngine created for call: uuid={uuid} client_id={client_id}")
            except Exception as e:
                self.logger.error(f"Failed to create FlowEngine for uuid={uuid} client_id={client_id}: {e}")
                # エラー時はデフォルトのFlowEngineを使用
                self.flow_engines[uuid] = self.flow_engine
        
        # セッション状態を初期化（フェーズをENTRYに設定）
        state = self._get_session_state(uuid)
        if state.phase == "ENTRY" or not state.phase:
            state.phase = "ENTRY"
            state.meta["client_id"] = client_id
            self.logger.info(f"Session state initialized: uuid={uuid} phase=ENTRY client_id={client_id}")
        
        # call_idを設定（ASR結果の処理で使用される）
        self.set_call_id(uuid)
        
        # GoogleASRのストリーミングを開始
        if hasattr(self.asr_model, '_start_stream_worker'):
            self.asr_model._start_stream_worker(uuid)
            self.logger.info(f"ASR enabled for call uuid={uuid} client_id={client_id}")
            # runtime.logへの主要イベント出力（詳細フォーマット）
            runtime_logger = logging.getLogger("runtime")
            runtime_logger.info(f"[ASR] start uuid={uuid} client_id={client_id}")
        else:
            self.logger.error(f"enable_asr: ASR model does not have _start_stream_worker method (uuid={uuid})")
    
    def _classify_simple_intent(self, text: str, normalized: str) -> Optional[str]:
        """
        簡易Intent判定（はい/いいえ/その他）
        
        :param text: 元のテキスト
        :param normalized: 正規化されたテキスト
        :return: "YES", "NO", "OTHER", または None（判定できない場合）
        """
        # 「はい」系のキーワード
        yes_keywords = ["はい", "ええ", "うん", "そうです", "そう", "了解", "りょうかい", "ok", "okです"]
        if any(kw in normalized for kw in yes_keywords):
            return "YES"
        
        # 「いいえ」系のキーワード
        no_keywords = ["いいえ", "いえ", "違います", "ちがいます", "違う", "ちがう", "no", "ノー"]
        if any(kw in normalized for kw in no_keywords):
            return "NO"
        
        # その他の場合はNoneを返す（通常の会話フロー処理に委譲）
        return None
    
    def _break_playback(self, call_id: str) -> None:
        break_playback(self, call_id)
    
    def _play_audio_response(self, call_id: str, intent: str) -> None:
        play_audio_response(self, call_id, intent)
    
    def _handle_flow_engine_transition(
        self,
        call_id: str,
        text: str,
        normalized_text: str,
        intent: str,
        state: ConversationState,
        flow_engine: FlowEngine,
        client_id: str
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
    
    def _render_templates_from_ids(self, template_ids: List[str], client_id: Optional[str] = None) -> str:
        return render_templates_from_ids(
            self.templates,
            template_ids,
            client_id,
            self.client_id,
            self.logger,
        )
    
    def _play_template_sequence(self, call_id: str, template_ids: List[str], client_id: Optional[str] = None) -> None:
        play_template_sequence(self, call_id, template_ids, client_id=client_id)
    
    def _send_playback_request_http(self, call_id: str, audio_file: str) -> None:
        send_playback_request_http(self, call_id, audio_file)
    
    def _save_debug_wav(self, pcm16k_bytes: bytes):
        save_debug_wav(self, pcm16k_bytes)
    

    def _is_hallucination(self, text):
        """Whisperの幻聴（繰り返しノイズ）を判定"""
        if not text: return True
        # 1. 「おかげで、おかげで」のような繰り返しを検知
        if len(text) > 15 and len(set(text)) < 8:
            return True
        # 2. Whisper特有の幻聴ワード
        hallucination_words = ["おかげで", "ご視聴", "字幕", "チャンネル登録", "おやすみなさい"]
        for hw in hallucination_words:
            if text.count(hw) > 2: # 2回以上出てきたらアウト
                return True
        return False

    def _get_session_state(self, call_id: str) -> ConversationState:
        return get_session_state(self, call_id)

    def _reset_session_state(self, call_id: Optional[str]) -> None:
        reset_session_state(self, call_id)
    
    def _start_activity_monitor(self) -> None:
        start_activity_monitor(self)
    
    def on_call_end(self, call_id: Optional[str], source: str = "unknown") -> None:
        manage_call_end(self, call_id, source=source)

    def cleanup_asr_instance(self, call_id: str) -> None:
        cleanup_asr_instance(self, call_id)

    def cleanup_call(self, call_id: str) -> None:
        cleanup_call(self, call_id)

    def _load_flow(self, client_id: str) -> dict:
        return load_flow(self, client_id)
    
    def _load_json(self, path: str, default: str = None) -> dict:
        return load_json(self, path, default=default)
    
    def _load_keywords_from_config(self) -> None:
        load_keywords_from_config(self)
    
        
    def _save_transcript_event(self, call_id: str, text: str, is_final: bool, kwargs: dict) -> None:
        save_transcript_event_from_core(self, call_id, text, is_final, kwargs)
    
    def _save_session_summary(self, call_id: str) -> None:
        save_session_summary_from_core(self, call_id)
    
    def reload_flow(self) -> None:
        """
        会話フロー・テンプレート・キーワードを再読み込みする
        """
        self.flow = self._load_flow(self.client_id)
        self.templates = self._load_json(
            f"/opt/libertycall/config/clients/{self.client_id}/templates.json",
            default="/opt/libertycall/config/system/default_templates.json"
        )
        self.keywords = self._load_json(
            f"/opt/libertycall/config/clients/{self.client_id}/keywords.json",
            default="/opt/libertycall/config/system/default_keywords.json"
        )
        self._load_keywords_from_config()
        self.logger.info(f"[FLOW] reloaded for client={self.client_id}")
    
    def set_client_id(self, client_id: str) -> None:
        """
        クライアントIDを変更して会話フローを再読み込みする
        
        :param client_id: 新しいクライアントID
        """
        self.client_id = client_id
        self.reload_flow()

    def _contains_keywords(self, normalized_text: str, keywords: List[str]) -> bool:
        if not normalized_text:
            return False
        return any(k for k in keywords if k and k in normalized_text)

    def _render_templates(self, template_ids: List[str]) -> str:
        return render_templates(template_ids)

    def _synthesize_text_with_gemini(self, text: str, speaking_rate: float = 1.0, pitch: float = 0.0) -> Optional[bytes]:
        """
        Gemini APIを使用してテキストから音声を合成する（日本語音声に最適化）
        
        :param text: 音声化するテキスト
        :param speaking_rate: 話す速度（デフォルト: 1.0）
        :param pitch: ピッチ（デフォルト: 0.0）
        :return: 音声データ（bytes）または None
        """
        if not self.use_gemini_tts:
            return None
        
        return synthesize_text_with_gemini(text, speaking_rate, pitch)

    def _synthesize_template_audio(self, template_id: str) -> Optional[bytes]:
        """
        テンプレIDから音声を合成する
        
        :param template_id: テンプレID
        :return: 音声データ（bytes）または None
        """
        if not self.use_gemini_tts:
            return None
        
        def get_template_config_with_client(template_id: str):
            # まず self.templates（クライアント固有）から読み込む
            if self.templates and template_id in self.templates:
                return self.templates[template_id]
            # クライアント固有にない場合はグローバルから読み込む
            return get_template_config(template_id)
        
        return synthesize_template_audio(template_id, get_template_config_with_client)

    def _synthesize_template_sequence(self, template_ids: List[str]) -> Optional[bytes]:
        """
        テンプレIDのリストから順番に音声を合成して結合する
        
        :param template_ids: テンプレIDのリスト
        :return: 結合された音声データ（bytes）または None
        """
        if not template_ids:
            return None
        
        def get_template_config_with_client(template_id: str):
            # まず self.templates（クライアント固有）から読み込む
            if self.templates and template_id in self.templates:
                return self.templates[template_id]
            # クライアント固有にない場合はグローバルから読み込む
            return get_template_config(template_id)
        
        return synthesize_template_sequence(template_ids, get_template_config_with_client)

    def _append_call_log(self, role: str, text: str, template_id: Optional[str] = None) -> None:
        append_call_log_entry(self, role, text, template_id=template_id)

    def _trigger_transfer(self, call_id: str) -> None:
        manage_trigger_transfer(self, call_id)

    def _trigger_transfer_if_needed(self, call_id: str, state: ConversationState) -> None:
        manage_trigger_transfer_if_needed(self, call_id, state)

    def _schedule_auto_hangup(self, call_id: str, delay_sec: float = 60.0) -> None:
        manage_schedule_auto_hangup(self, call_id, delay_sec=delay_sec)

    def on_call_start(self, call_id: str, client_id: str = None, **kwargs) -> None:
        manage_call_start(self, call_id, client_id=client_id, **kwargs)

    def _handle_entry_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_entry_phase(self, call_id, raw_text, normalized_text, state)

    def _handle_qa_phase(
        self,
        call_id: str,
        raw_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_qa_phase(self, call_id, raw_text, state)

    def _handle_after_085_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_after_085_phase(self, call_id, raw_text, normalized_text, state)

    def _handle_entry_confirm_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_entry_confirm_phase(self, call_id, raw_text, normalized_text, state)
    
    def _handle_waiting_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_waiting_phase(self, call_id, raw_text, normalized_text, state)
    
    def _handle_not_heard_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_not_heard_phase(self, call_id, raw_text, normalized_text, state)

    def _handle_closing_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_closing_phase(self, call_id, raw_text, normalized_text, state)

    def _handle_handoff_confirm(
        self,
        call_id: str,
        raw_text: str,
        intent: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], str, bool]:
        return handle_handoff_confirm(self, call_id, raw_text, intent, state)

    def _handle_handoff_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        return handle_handoff_phase(self, call_id, raw_text, normalized_text, state)

    def _run_conversation_flow(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[List[str], str, bool]:
        return run_conversation_flow(self, call_id, raw_text)

    def _generate_reply(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[str, List[str], str, bool]:
        return generate_reply(self, call_id, raw_text)

    def process_dialogue(self, pcm16k_bytes):
        # 0. WAV保存（デバッグ用、Whisperに渡す直前の音声を保存）
        if not self._wav_saved:  # 1通話あたり最初の1回だけ保存
            self._save_debug_wav(pcm16k_bytes)
        
        # 1. 音声認識 (ASR)
        text = self.asr_model.transcribe_pcm16(pcm16k_bytes)  # type: ignore[union-attr]
        self.logger.info(f"ASR Result: '{text}'")

        # ★幻聴フィルター
        if self._is_hallucination(text):
            self.logger.debug(">> Ignored hallucination (noise)")
            # ログ用に text と 'IGNORE' を返す
            return None, False, text, "IGNORE", ""
        state_key = self.call_id or "BATCH_CALL"
        resp_text, template_ids, intent, transfer_requested = self._generate_reply(state_key, text)
        self.logger.info(
            "CONV_FLOW_BATCH: call_id=%s phase=%s intent=%s templates=%s",
            state_key,
            self._get_session_state(state_key).phase,
            intent,
            template_ids,
        )
        if transfer_requested:
            self._trigger_transfer(state_key)
        should_transfer = transfer_requested

        # 4. 音声合成 (TTS) - template_ids ベースで合成
        tts_audio = None
        if template_ids and self.use_gemini_tts:
            tts_audio = self._synthesize_template_sequence(template_ids)
            if not tts_audio:
                self.logger.debug("TTS synthesis failed for template_ids=%s", template_ids)
        elif not resp_text:
            self.logger.debug("No response text generated; skipping TTS synthesis.")
        else:
            self.logger.debug("TTS クライアント未初期化のため音声合成をスキップしました。")
        
        # 音声データ, 転送フラグ, テキスト, 意図 の4つを返す
        return tts_audio, should_transfer, text, intent, resp_text

    def on_new_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
        handle_new_audio(self, call_id, pcm16k_bytes)

    def _on_asr_error(self, call_id: str, error: Exception) -> None:
        """
        GoogleASR がストリームエラー（Audio Timeout など）を起こしたときに呼ばれる。
        無音で終わらないように、フォールバック発話＋必要なら担当者ハンドオフに寄せる。
        
        :param call_id: 通話ID
        :param error: エラーオブジェクト（エラータイプによって処理を変える可能性がある）
        
        注意:
        - Audio Timeout などの一時的なエラー: フォールバック発話 + ハンドオフ
        - 認証エラーなどの永続的なエラー: ログのみ（フォールバック発話は出さない）
        - tts_callback が未設定の場合: 転送のみ実行（発話なし）
        """
        error_type = type(error).__name__
        error_msg = str(error)
        self.logger.warning(
            f"ASR_ERROR_HANDLER: call_id={call_id} error_type={error_type} error={error_msg!r}"
        )
        key = call_id or "GLOBAL_CALL"
        state = self._get_session_state(call_id)
        
        # すでにハンドオフ完了状態（担当者への転送フローを出し終わっている）なら何もしない
        # ※この場合だけ「二重に転送案内をしゃべらない」ようにする
        if state.handoff_state == "done" and state.transfer_requested:
            self.logger.info(f"ASR_ERROR_HANDLER: handoff already done (call_id={call_id})")
            return
        
        # 認証エラーなどの永続的なエラーの場合は、フォールバック発話を出さない
        # （ユーザーに誤解を与えないため）
        is_permanent_error = any(keyword in error_msg.lower() for keyword in [
            "credentials", "authentication", "permission", "unauthorized",
            "forbidden", "not found", "invalid"
        ])
        
        if is_permanent_error:
            self.logger.error(
                f"ASR_ERROR_HANDLER: permanent error detected (call_id={call_id}), "
                f"skipping fallback speech. Error: {error_msg}"
            )
            # 永続的なエラーの場合は転送も実行しない（システムエラーとして扱う）
            return
        
        # フォールバック文言（テンプレではなく生テキストで OK）
        fallback_text = "恐れ入ります。うまくお話をお伺いできませんでしたので、担当者におつなぎいたします。"
        
        # 状態を「転送要求あり」にしておく
        state.handoff_state = "done"
        state.handoff_retry_count = 0
        state.handoff_prompt_sent = True
        state.transfer_requested = True
        self._trigger_transfer_if_needed(call_id, state)
        state.last_intent = "HANDOFF_ERROR_FALLBACK"
        
        # gateway 側に「転送前の一言」として渡す
        # 注意: tts_callback が未設定の場合でも転送は実行される（発話なし）
        if hasattr(self, "tts_callback") and self.tts_callback:  # type: ignore[attr-defined]
            try:
                # 081/082 に合わせたニュアンスなので template_ids は ["081", "082"] にしておく
                template_ids = ["081", "082"]
                try:
                    # 再生予定テキスト（優先して生テキスト、なければテンプレから取得）
                    self.current_system_text = fallback_text or self._render_templates(template_ids) or ""
                except Exception:
                    try:
                        self.current_system_text = fallback_text or ""
                    except Exception:
                        self.current_system_text = ""
                self.tts_callback(call_id, fallback_text, template_ids, True)  # type: ignore[misc, attr-defined]
                self.logger.info(
                    f"ASR_ERROR_HANDLER: TTS fallback sent (call_id={call_id}, text={fallback_text})"
                )
            except Exception as e:
                self.logger.exception(f"ASR_ERROR_HANDLER: tts_callback error (call_id={call_id}): {e}")
        else:
            self.logger.warning(
                f"ASR_ERROR_HANDLER: tts_callback not set (call_id={call_id}), "
                f"transfer will proceed without fallback speech"
            )

    def on_transcript(self, call_id: str, text: str, is_final: bool = True, **kwargs) -> Optional[str]:
        return handle_transcript(self, call_id, text, is_final=is_final, **kwargs)
    
    def _log_ai_templates(self, template_ids: List[str]) -> None:
        log_ai_templates(self, template_ids)
    
    def _cleanup_stale_partials(self, max_age_sec: float = 30.0) -> None:
        """
        古いpartial transcriptsをクリーンアップ
        
        :param max_age_sec: 最大保持時間（秒）。デフォルト: 30秒
        """
        now = time.time()
        stale_keys = [
            call_id for call_id, data in self.partial_transcripts.items()
            if now - data.get("updated", 0) > max_age_sec
        ]
        for key in stale_keys:
            self.logger.warning(
                f"PARTIAL_CLEANUP: removing stale partial for call_id={key} "
                f"(age={now - self.partial_transcripts[key].get('updated', 0):.1f}s)"
            )
            del self.partial_transcripts[key]
    
    def check_for_transcript(self, call_id: str) -> Optional[Tuple[str, float, float, float]]:
        """
        ストリーミングモード: 確定した発話があればテキストを返す。
        
        :param call_id: 通話ID
        :return: (text, audio_duration_sec, inference_time_sec, end_to_text_delay_sec) または None
        """
        if not self.streaming_enabled:
            return None

        # 【修正】asr_model が None の場合は安全にリターン（初期化失敗や認証エラーで None になる）
        if self.asr_model is None:
            # 頻繁に出る可能性があるため WARNING を吐かない（必要ならデバッグ用に変更可）
            return None

        # poll_result 呼び出し時に競合で asr_model が None になる可能性もあるため例外を吸収
        try:
            result = self.asr_model.poll_result(call_id)  # type: ignore[union-attr]
        except AttributeError:
            # 万が一 asr_model が途中で None に変わっていた場合、安全に無視して None を返す
            return None

        if result is None:
            return None

        # poll_resultは既に (text, audio_duration, inference_time, end_to_text_delay) を返す
        return result

    def reset_call(self, call_id: str) -> None:
        manage_reset_call(self, call_id)