import logging

logger = logging.getLogger(__name__)
logger.error("!!! CRITICAL_LOAD: ai_core.py is LOADED from /opt/libertycall !!!")

import numpy as np
import os
# 明示的に認証ファイルパスを指定（存在する候補ファイルがあればデフォルトで設定）
# 実稼働では環境変数で設定するのが望ましいが、ここでは一時的にデフォルトを補完する
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/opt/libertycall/config/google-credentials.json")
import wave
import time
import threading
import queue
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any, Callable
from dataclasses import dataclass
# Gemini API インポート
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ModuleNotFoundError:
    genai = None
    GEMINI_AVAILABLE = False

from .text_utils import (
    get_response_template,
    get_template_config,
    normalize_text,
    interpret_handoff_reply,
    normalize_text_for_comparison,
)
from .flow_engine import FlowEngine
from .dialogue_flow import get_response as dialogue_get_response
from .tts_utils import (
    synthesize_text_with_gemini,
    synthesize_template_audio,
    synthesize_template_sequence,
)
from .google_asr import GoogleASR
from .state_logic import ConversationState, MisunderstandingGuard, HandoffStateMachine
from .session_utils import (
    get_session_dir,
    ensure_session_dir,
    save_transcript_event,
    save_session_summary,
    append_call_log,
    cleanup_stale_sessions,
)

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
        
        # クライアントごとの会話フロー・テンプレート・キーワードを読み込む
        self.flow = self._load_flow(client_id)
        self.templates = self._load_json(
            f"/opt/libertycall/config/clients/{client_id}/templates.json",
            default="/opt/libertycall/config/system/default_templates.json"
        )
        self.keywords = self._load_json(
            f"/opt/libertycall/config/clients/{client_id}/keywords.json",
            default="/opt/libertycall/config/system/default_keywords.json"
        )
        
        # FlowEngineを初期化（JSON定義ベースのフェーズ遷移エンジン）
        # デフォルトクライアント用のFlowEngineを初期化（後でUUIDごとに追加される）
        self.flow_engine = FlowEngine(client_id=client_id)
        
        # UUIDごとのFlowEngineを管理する辞書（クライアント別フロー対応）
        self.flow_engines: Dict[str, FlowEngine] = {}
        
        # UUIDごとのclient_idを管理する辞書（call_id -> client_id）
        self.call_client_map: Dict[str, str] = {}
        
        # UUIDごとの再生状態を管理する辞書（call_id -> is_playing）
        self.is_playing: Dict[str, bool] = {}
        
        # UUIDごとの最終活動時刻を管理する辞書（call_id -> last_activity_timestamp）
        self.last_activity: Dict[str, float] = {}
        
        # テンプレート再生履歴を管理する辞書（call_id -> {template_id: last_play_time}）
        # 同じテンプレートを短時間で連続再生しないようにする
        self.last_template_play: Dict[str, Dict[str, float]] = {}
        
        # セッション情報を管理する辞書（call_id -> session_info）
        self.session_info: Dict[str, Dict[str, Any]] = {}
        
        # FreeSWITCH ESL接続への参照（uuid_break用）
        self.esl_connection = None
        
        # 無音タイムアウト監視スレッド
        self._activity_monitor_thread = None
        self._activity_monitor_running = False
        self._start_activity_monitor()
        
        self.logger.info(f"FlowEngine initialized for default client: {client_id}")
        
        # キーワードをインスタンス変数として設定（後方互換性のため）
        self._load_keywords_from_config()
        self.call_id = None
        self.caller_number = None
        self.log_session_id = None  # 通話ログ用のセッションID（call_idがない場合に使用）
        self.session_states: Dict[str, Dict[str, Any]] = {}
        # 【追加】partial transcripts を保持（call_id ごとに管理）
        self.partial_transcripts: Dict[str, Dict[str, Any]] = {}
        self.debug_save_wav = False
        self.call_id = None
        self._wav_saved = False
        self._wav_chunk_counter = 0
        self.asr_model = None
        self.transfer_callback: Optional[Callable[[str], None]] = None
        self.hangup_callback: Optional[Callable[[str], None]] = None
        self.playback_callback: Optional[Callable[[str, str], None]] = None
        self._auto_hangup_timers: Dict[str, threading.Timer] = {}
        # 二重再生防止: on_call_start() を呼び出し済みの通話IDセット（全クライアント共通）
        self._call_started_calls: set[str] = set()
        # 二重再生防止: 冒頭テンプレート（000-002）を再生済みの通話IDセット（001専用）
        self._intro_played_calls: set[str] = set()
        # 通話開始イベントの最終時刻を管理（call_id -> last_start_timestamp）
        self.last_start_times: Dict[str, float] = {}
        # 現在システムが再生しているテキスト（エコー除去用）
        self.current_system_text: str = ""
        # 【追加】テンプレートID->テキスト辞書（エコー判定用の簡易辞書）
        self.TEMPLATE_TEXTS: Dict[str, str] = {
            "000": "この電話は応対品質の向上と正確なご案内のため録音させていただいております",
            "004": "お電話ありがとうございます",
            "006_SYS": "ただいま電話に出ることができません",
            "081": "もしもし、聞こえていますでしょうか",
            "110": "発信音の後にメッセージを入れてください",
        }
        
        # AI_CORE_VERSION ログ（編集した ai_core.py が読まれているか確認用）
        self.logger.info(
            "AI_CORE_VERSION: version=2025-12-01-auto-hangup hangup_callback=%s",
            "set" if self.hangup_callback else "none"
        )
        
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
        """
        Gemini API TTS の初期化（クライアント別設定対応）
        """
        # ChatGPT音声風: TTSを完全非同期化するためのThreadPoolExecutorを初期化
        from concurrent.futures import ThreadPoolExecutor
        self.tts_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TTS")
        self.logger.debug("AICore: TTS ThreadPoolExecutor initialized (max_workers=2)")

        # WAV保存機能の設定
        self.debug_save_wav = os.getenv("LC_DEBUG_SAVE_WAV", "0") == "1"
        self.call_id = None
        self._wav_saved = False  # 1通話あたり最初の1回だけ保存
        self._wav_chunk_counter = 0
        
        # クライアント別TTS設定辞書
        # クライアント001はテンポ早め設定、002はゆっくりで穏やか
        TTS_CONFIGS = {
            "000": {
                "voice": "ja-JP-Neural2-B",
                "pitch": 0.0,
                "speaking_rate": 1.2
            },
            "001": {
                "voice": "ja-JP-Neural2-B",
                "pitch": 2.0,
                "speaking_rate": 1.2
            },
            "002": {
                "voice": "ja-JP-Wavenet-C",
                "pitch": 0.5,
                "speaking_rate": 1.0
            }
        }
        
        # クライアントIDに基づいてTTS設定を取得（fallback: 000）
        tts_conf = TTS_CONFIGS.get(self.client_id, TTS_CONFIGS["000"])
        
        # Gemini API設定
        self.use_gemini_tts = False
        self.gemini_model = None
        
        # Gemini API認証情報の確認
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        
        # Gemini APIの初期化
        if not GEMINI_AVAILABLE or not genai:
            self.logger.error("[TTS_INIT] Gemini API (google-generativeai) が利用できません。インストールしてください: pip install google-generativeai")
            return
        
        try:
            if gemini_api_key:
                genai.configure(api_key=gemini_api_key)
                self.use_gemini_tts = True
                self.logger.info("[TTS_INIT] Gemini API認証成功 (APIキー使用)")
            elif google_creds:
                # サービスアカウントキーを使用する場合
                # 注: Gemini APIは主にAPIキーを使用しますが、サービスアカウントもサポートされる場合があります
                try:
                    # サービスアカウントキーからAPIキーを取得するか、直接認証を試行
                    genai.configure(api_key=None)  # サービスアカウント認証を試行
                    self.use_gemini_tts = True
                    self.logger.info("[TTS_INIT] Gemini API認証成功 (サービスアカウント使用)")
                except Exception as e:
                    self.logger.error(f"[TTS_INIT] Gemini API認証失敗 (サービスアカウント): {e}")
                    return
            else:
                self.logger.error("[TTS_INIT] Gemini API認証情報が未設定です。GEMINI_API_KEYまたはGOOGLE_APPLICATION_CREDENTIALSを設定してください。")
                return
        except Exception as e:
            self.logger.error(f"[TTS_INIT] Gemini API初期化エラー: {e}")
            return
        
        # Gemini API設定を保存
        self.tts_config = tts_conf
        # TTS設定ログ出力
        self.logger.info(
            f"[TTS_PROFILE] client={self.client_id} voice={tts_conf['voice']} "
            f"speed={tts_conf['speaking_rate']} pitch={tts_conf['pitch']} (Gemini API)"
        )
    
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
        """
        FreeSWITCHで再生中の音声を中断する（uuid_break）
        
        非同期実行で応答速度を最適化
        
        :param call_id: 通話UUID
        """
        if not self.esl_connection:
            self.logger.warning(f"[BREAK_PLAYBACK] ESL not available: call_id={call_id}")
            return
        
        if not self.esl_connection.connected():
            self.logger.warning(f"[BREAK_PLAYBACK] ESL not connected: call_id={call_id}")
            return
        
        # 非同期実行で応答速度を最適化（bgapiを使用）
        def _break_playback_async():
            try:
                # bgapiを使って非同期実行（応答を待たない）
                result = self.esl_connection.bgapi("uuid_break", call_id)
                
                if result:
                    reply_text = result.getHeader('Reply-Text') if hasattr(result, 'getHeader') else None
                    if reply_text and '+OK' in reply_text:
                        self.logger.info(f"[BREAK_PLAYBACK] Playback interrupted: call_id={call_id}")
                    else:
                        self.logger.debug(
                            f"[BREAK_PLAYBACK] Break command sent (async): call_id={call_id} "
                            f"reply={reply_text}"
                        )
                else:
                    self.logger.debug(f"[BREAK_PLAYBACK] Break command sent (async): call_id={call_id}")
            except Exception as e:
                self.logger.exception(f"[BREAK_PLAYBACK] Failed to break playback: call_id={call_id} error={e}")
        
        # スレッドで非同期実行（メイン処理をブロックしない）
        import threading
        thread = threading.Thread(target=_break_playback_async, daemon=True)
        thread.start()
        self.logger.debug(f"[BREAK_PLAYBACK] Break command queued (async): call_id={call_id}")
    
    def _play_audio_response(self, call_id: str, intent: str) -> None:
        """
        FreeSWITCHに音声再生リクエストを送信
        
        :param call_id: 通話UUID
        :param intent: 簡易Intent（"YES", "NO", "OTHER"）
        """
        # Intentに応じて音声ファイルを決定
        audio_files = {
            "YES": "/opt/libertycall/clients/000/audio/yes_8k.wav",
            "NO": "/opt/libertycall/clients/000/audio/no_8k.wav",
            "OTHER": "/opt/libertycall/clients/000/audio/repeat_8k.wav",
        }
        
        audio_file = audio_files.get(intent)
        if not audio_file:
            self.logger.warning(f"_play_audio_response: Unknown intent {intent}")
            return
        
        # 音声ファイルの存在確認
        if not Path(audio_file).exists():
            self.logger.warning(f"_play_audio_response: Audio file not found: {audio_file}")
            # フォールバック: 既存のファイルを使用
            if intent == "YES":
                audio_file = "/opt/libertycall/clients/000/audio/110_8k.wav"  # 既存のファイル
            elif intent == "NO":
                audio_file = "/opt/libertycall/clients/000/audio/111_8k.wav"  # 既存のファイル
            else:
                audio_file = "/opt/libertycall/clients/000/audio/110_8k.wav"  # デフォルト
        
        # FreeSWITCHへの音声再生リクエストを送信
        # 方法1: transferを使ってplay_audio_dynamicエクステンションに転送
        # 方法2: HTTP API経由でFreeSWITCHにリクエスト（実装が必要）
        # ここでは、playback_callbackが設定されている場合はそれを使用、なければHTTP APIを試行
        if hasattr(self, 'playback_callback') and self.playback_callback:
            try:
                self.playback_callback(call_id, audio_file)
                self.logger.info(f"[PLAYBACK] Sent audio playback request: call_id={call_id} file={audio_file}")
            except Exception as e:
                self.logger.exception(f"[PLAYBACK] Failed to send playback request: {e}")
        else:
            # HTTP API経由でFreeSWITCHにリクエスト
            self._send_playback_request_http(call_id, audio_file)
    
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
        """
        FlowEngineを使ってフェーズ遷移とテンプレート選択を行う
        
        :param call_id: 通話ID
        :param text: 元のテキスト
        :param normalized_text: 正規化されたテキスト
        :param intent: 判定されたIntent
        :param state: セッション状態
        :return: (reply_text, template_ids, intent, transfer_requested)
        """
        current_phase = state.phase or "ENTRY"
        
        # コンテキスト情報を構築
        context = {
            "intent": intent or "UNKNOWN",
            "text": text,
            "normalized_text": normalized_text,
            "keywords": self.keywords,
            "user_reply_received": bool(text and len(text.strip()) > 0),
            "user_voice_detected": bool(text and len(text.strip()) > 0),
            "timeout": False,
            "is_first_sales_call": getattr(state, "is_first_sales_call", False),
        }
        
        # FlowEngineでフェーズ遷移を決定
        next_phase = flow_engine.transition(current_phase, context)
        
        # フェーズを更新
        if next_phase != current_phase:
            state.phase = next_phase
            self.logger.info(
                f"[FLOW_ENGINE] Phase transition: {current_phase} -> {next_phase} "
                f"(call_id={call_id}, client_id={client_id}, intent={intent})"
            )
        
        # フェーズ遷移のテンプレート選択ロジック
        # ENTRY -> 他フェーズの遷移時は、ENTRYのテンプレートを使用
        # それ以外は次のフェーズのテンプレートを使用
        if current_phase == "ENTRY" and next_phase != "ENTRY":
            template_ids = flow_engine.get_templates(current_phase)
            self.logger.info(f"[FLOW_ENGINE] Using ENTRY phase templates for transition: {current_phase} -> {next_phase}")
        else:
            template_ids = flow_engine.get_templates(next_phase)
        
        # テンプレートが空の場合は、現在のフェーズのテンプレートを使用
        if not template_ids:
            template_ids = flow_engine.get_templates(current_phase)
        
        # テンプレートIDリストから実際に使用するテンプレートを選択
        # 複数のテンプレートIDがある場合は、リストの最初の要素を使用
        if template_ids and len(template_ids) > 1:
            # Intent方式は削除されました。リストの最初の要素を使用
            try:
                # 選択できない場合は、リストの最初の要素を使用
                template_ids = [template_ids[0]]
            except Exception as e:
                self.logger.warning(f"[FLOW_ENGINE] Failed to select template: {e}, using first template")
                template_ids = [template_ids[0]]
        elif template_ids and len(template_ids) == 1:
            # 1つのテンプレートIDのみの場合はそのまま使用
            pass
        else:
            # テンプレートIDがない場合は、フォールバック（110を使用）
            template_ids = ["110"]
        
        # テンプレートから返答テキストを生成（クライアント別templates.jsonを使用）
        reply_text = self._render_templates_from_ids(template_ids, client_id=client_id) if template_ids else ""
        
        # 転送要求の判定（HANDOFF_DONEフェーズの場合）
        transfer_requested = (next_phase == "HANDOFF_DONE")
        
        return reply_text, template_ids, intent, transfer_requested
    
    def _render_templates_from_ids(self, template_ids: List[str], client_id: Optional[str] = None) -> str:
        """
        テンプレートIDのリストから返答テキストを生成
        
        :param template_ids: テンプレートIDのリスト
        :param client_id: クライアントID（指定されない場合はself.client_idを使用）
        :return: 結合された返答テキスト
        """
        effective_client_id = client_id or self.client_id or "000"
        texts = []
        
        for template_id in template_ids:
            # クライアント別のtemplates.jsonからテキストを取得
            template_config = None
            
            # まず、指定されたクライアントIDのtemplates.jsonを読み込む
            if client_id and client_id != self.client_id:
                try:
                    client_templates_path = f"/opt/libertycall/config/clients/{client_id}/templates.json"
                    if Path(client_templates_path).exists():
                        with open(client_templates_path, 'r', encoding='utf-8') as f:
                            import json
                            client_templates = json.load(f)
                            template_config = client_templates.get(template_id)
                except Exception as e:
                    self.logger.debug(f"Failed to load client templates for {client_id}: {e}")
            
            # クライアント別のtemplates.jsonが見つからない場合は、self.templatesを使用
            if not template_config:
                template_config = self.templates.get(template_id)
            
            if template_config and isinstance(template_config, dict):
                text = template_config.get("text", "")
                if text:
                    texts.append(text)
            else:
                # フォールバック: intent_rulesから取得
                try:
                    from .text_utils import get_response_template
                    text = get_response_template(template_id)
                    if text:
                        texts.append(text)
                except Exception:
                    pass
        
        return " ".join(texts) if texts else ""
    
    def _play_template_sequence(self, call_id: str, template_ids: List[str], client_id: Optional[str] = None) -> None:
        """
        テンプレートIDのシーケンスをFreeSWITCHで再生
        
        応答速度最適化: 再生完了を待たずに即座にすべてのテンプレートを再生開始
        FreeSWITCHは自動的に順番に再生するため、待機は不要
        
        :param call_id: 通話UUID
        :param template_ids: テンプレートIDのリスト（例: ["006", "085"]）
        :param client_id: クライアントID（指定されない場合はself.client_idを使用）
        """
        if not template_ids:
            return
        
        # クライアントIDの決定
        effective_client_id = client_id or self.call_client_map.get(call_id) or self.client_id or "000"
        
        # テンプレート再生履歴の初期化
        if call_id not in self.last_template_play:
            self.last_template_play[call_id] = {}
        
        current_time = time.time()
        # 重複防止: 同じテンプレートを10秒以内に連続再生しない
        DUPLICATE_PREVENTION_SEC = 10.0
        
        # 【修正2】再生キューの即時処理: 最初のテンプレートでUUID更新を確実に実行
        # 最初のテンプレート再生前にUUIDを更新し、失敗したテンプレートも含めて確実に順番通り再生
        failed_templates = []  # 失敗したテンプレートを記録
        
        # 応答速度最適化: すべてのテンプレートを即座に再生開始（待機なし）
        # 【追加】再生前に再生予定のテキストを記録しておく（ASR側でエコー除去に使用）
        try:
            try:
                combined_text = self._render_templates(template_ids) if template_ids else ""
            except Exception:
                combined_text = " ".join(template_ids) if template_ids else ""
            self.current_system_text = combined_text or ""
        except Exception:
            pass
        # FreeSWITCHは自動的に順番に再生するため、各再生の完了を待つ必要はない
        for template_id in template_ids:
            # 【修正2改善】重複防止: 同じテンプレートを10秒以内に連続再生しない
            if call_id not in self.last_template_play:
                self.last_template_play[call_id] = {}
            
            last_play_time = self.last_template_play[call_id].get(template_id, 0)
            time_since_last_play = current_time - last_play_time
            
            if time_since_last_play < DUPLICATE_PREVENTION_SEC and last_play_time > 0:
                self.logger.info(
                    f"[PLAY_TEMPLATE] Skipping recently played template: call_id={call_id} "
                    f"template_id={template_id} time_since_last={time_since_last_play:.2f}s"
                )
                continue
            
            # 【修正1】テンプレートIDから音声ファイルパスを生成（絶対パス、クライアント別ディレクトリ）
            # 絶対パスで固定（ディレクトリ階層の問題を回避）
            audio_dir = Path(f"/opt/libertycall/clients/{effective_client_id}/audio")
            
            # ファイル名の候補（優先順位: .wav → _8k.wav → _8k_norm.wav）
            audio_file_plain = audio_dir / f"{template_id}.wav"
            audio_file_regular = audio_dir / f"{template_id}_8k.wav"
            audio_file_norm = audio_dir / f"{template_id}_8k_norm.wav"
            
            # ファイル存在確認（優先順位順）
            audio_file = None
            checked_paths = []
            for candidate in [audio_file_plain, audio_file_regular, audio_file_norm]:
                checked_paths.append(str(candidate))
                if candidate.exists():
                    audio_file = str(candidate)
                    self.logger.debug(
                        f"[PLAY_TEMPLATE] Found audio file: template_id={template_id} file={audio_file}"
                    )
                    break
            
            if not audio_file:
                # 音声ファイルが存在しない場合は警告を出力し、デフォルトテンプレート（001）にフォールバック
                self.logger.warning(
                    f"[PLAY_TEMPLATE] Audio file not found: template_id={template_id} "
                    f"checked_paths={checked_paths} audio_dir={audio_dir}"
                )
                # runtime.logにも警告を出力
                runtime_logger = logging.getLogger("runtime")
                runtime_logger.warning(f"[FLOW] Missing template audio: call_id={call_id} template_id={template_id}")
                
                # フォールバック: デフォルトテンプレート（001）を試す
                fallback_template_id = "001"
                fallback_file = audio_dir / f"{fallback_template_id}.wav"
                if fallback_file.exists():
                    audio_file = str(fallback_file)
                    self.logger.info(
                        f"[PLAY_TEMPLATE] Using fallback template: template_id={template_id} -> fallback={fallback_template_id} file={audio_file}"
                    )
                else:
                    self.logger.error(
                        f"[PLAY_TEMPLATE] Fallback template also not found: {fallback_file}"
                    )
                    continue
            
            # FreeSWITCHへの音声再生リクエストを送信（即時発火、待機なし）
            if hasattr(self, 'playback_callback') and self.playback_callback:
                try:
                    self.playback_callback(call_id, audio_file)
                    # 再生履歴を更新
                    self.last_template_play[call_id][template_id] = current_time
                    self.logger.info(
                        f"[PLAY_TEMPLATE] Sent playback request (immediate): "
                        f"call_id={call_id} template_id={template_id} file={audio_file}"
                    )
                except Exception as e:
                    self.logger.exception(
                        f"[PLAY_TEMPLATE] Failed to send playback request: call_id={call_id} template_id={template_id} error={e}"
                    )
                    # 失敗したテンプレートを記録（後でリトライ）
                    failed_templates.append((template_id, audio_file))
            else:
                # フォールバック: HTTP API経由
                try:
                    self._send_playback_request_http(call_id, audio_file)
                except Exception as e:
                    self.logger.exception(
                        f"[PLAY_TEMPLATE] HTTP playback request failed: call_id={call_id} template_id={template_id} error={e}"
                    )
                    failed_templates.append((template_id, audio_file))
        
        # 【修正2】失敗したテンプレートのリトライ（UUID更新後に再試行）
        if failed_templates:
            self.logger.info(
                f"[PLAY_TEMPLATE] Retrying {len(failed_templates)} failed templates after UUID update: call_id={call_id}"
            )
            # 短い待機時間後にリトライ（UUID更新の完了を待つ）
            # 注意: timeモジュールはファイル先頭で既にインポート済み
            time.sleep(0.1)  # 100ms待機
            
            for template_id, audio_file in failed_templates:
                if hasattr(self, 'playback_callback') and self.playback_callback:
                    try:
                        self.playback_callback(call_id, audio_file)
                        self.last_template_play[call_id][template_id] = time.time()
                        self.logger.info(
                            f"[PLAY_TEMPLATE] Retry successful: call_id={call_id} template_id={template_id} file={audio_file}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"[PLAY_TEMPLATE] Retry failed: call_id={call_id} template_id={template_id} error={e}"
                        )
    
    def _send_playback_request_http(self, call_id: str, audio_file: str) -> None:
        """
        FreeSWITCHにHTTP API経由で音声再生リクエストを送信
        
        :param call_id: 通話UUID
        :param audio_file: 音声ファイルのパス
        """
        try:
            import requests
            
            # FreeSWITCHのHTTP APIエンドポイント（mod_curl経由）
            # 注意: FreeSWITCHの標準的なHTTP APIはEvent Socket Interface (ESL) 経由
            # ここでは、transferを使ってplay_audio_dynamicエクステンションに転送する方法を使用
            # 実際の実装では、FreeSWITCHのEvent Socket Interface (ESL) を使う方が確実
            
            # 方法1: transferを使ってplay_audio_dynamicエクステンションに転送
            # FreeSWITCHのEvent Socket Interface (ESL) を使ってuuid_transferを実行
            # ただし、ここでは簡易的にHTTPリクエストを試行（実装が必要な場合はESLを使用）
            
            # 注意: この実装は簡易版。本番環境ではFreeSWITCHのEvent Socket Interface (ESL) を使用することを推奨
            self.logger.warning(
                f"[PLAYBACK] HTTP API not implemented yet. "
                f"Please use playback_callback or implement ESL connection. "
                f"call_id={call_id} file={audio_file}"
            )
            
            # TODO: FreeSWITCHのEvent Socket Interface (ESL) を使ってuuid_transferを実行
            # または、FreeSWITCHのHTTP APIエンドポイントを実装
            
        except ImportError:
            self.logger.error("[PLAYBACK] requests module not available")
        except Exception as e:
            self.logger.exception(f"[PLAYBACK] Failed to send HTTP request: {e}")
    
    def _save_debug_wav(self, pcm16k_bytes: bytes):
        """Whisperに渡す直前のPCM音声をWAVファイルとして保存"""
        if not self.debug_save_wav:
            return
        
        # 1通話あたり最初の1回だけ保存（5-10秒分を想定）
        # ただし、短すぎる場合はスキップ
        sample_rate = 16000
        duration_sec = len(pcm16k_bytes) / 2 / sample_rate  # PCM16なので2バイト/サンプル
        
        if duration_sec < 1.0:  # 1秒未満はスキップ
            return
        
        # 保存先ディレクトリを作成
        debug_dir = Path("/opt/libertycall/debug_audio")
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        # ファイル名を生成
        call_id_str = self.call_id or "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._wav_chunk_counter += 1
        filename = f"call_{call_id_str}_chunk_{self._wav_chunk_counter:03d}_{timestamp}.wav"
        filepath = debug_dir / filename
        
        # WAVファイルに保存
        try:
            with wave.open(str(filepath), 'wb') as wav_file:
                wav_file.setnchannels(1)  # モノラル
                wav_file.setsampwidth(2)   # 16bit = 2 bytes
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm16k_bytes)
            
            # ログ出力
            self.logger.info(
                f"ASR_DEBUG: saved debug WAV for call_id={call_id_str} "
                f"path={filepath} sr={sample_rate} duration={duration_sec:.2f}s"
            )
            self._wav_saved = True
        except Exception as e:
            self.logger.error(f"Failed to save debug WAV: {e}")

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
        key = call_id or "GLOBAL_CALL"
        if key not in self.session_states:
            # クライアントIDを取得（既存のマッピングから）
            client_id = self.call_client_map.get(call_id) or self.client_id or "000"
            
            self.session_states[key] = {
                "phase": "ENTRY",
                "last_intent": None,
                "handoff_state": "idle",
                "handoff_retry_count": 0,
                "transfer_requested": False,
                "transfer_executed": False,
                "handoff_prompt_sent": False,
                "not_heard_streak": 0,
                "unclear_streak": 0,  # AI がよくわからない状態で返答した回数
                "handoff_completed": False,
                "last_ai_templates": [],
                "meta": {"client_id": client_id},  # クライアントIDをmetaに保存
            }
        return ConversationState(self.session_states[key])

    def _reset_session_state(self, call_id: Optional[str]) -> None:
        """
        セッション状態をリセット（通話終了時など）
        
        注意: reset_call() から呼ばれるため、基本的には通話終了時のみ呼ばれる。
        ただし、再接続時に call_id が変わらない場合は、on_call_end() で明示的にクリアすることを推奨。
        """
        if not call_id:
            return
        self.session_states.pop(call_id, None)
        # セッション状態のみクリア（フラグは on_call_end() でクリア）
        # last_activityもクリア
        self.last_activity.pop(call_id, None)
    
    def _start_activity_monitor(self) -> None:
        """
        無音タイムアウト監視スレッドを開始
        
        ASR無音10秒でFlowEngine.transition("NOT_HEARD")を呼び出す
        """
        if self._activity_monitor_running:
            return
        
        def _activity_monitor_worker():
            """無音タイムアウト監視ワーカースレッド"""
            self._activity_monitor_running = True
            self.logger.info("[ACTIVITY_MONITOR] Started activity monitor thread")
            
            while self._activity_monitor_running:
                try:
                    time.sleep(1.0)  # 1秒ごとにチェック
                    
                    current_time = time.time()
                    timeout_sec = 10.0  # 無音タイムアウト: 10秒
                    
                    # 【修正3】古いセッションの強制クリーンアップ
                    # 現在の稼働中のcall_idを取得（_active_callsから）
                    active_call_ids = set()
                    if hasattr(self, 'gateway') and hasattr(self.gateway, '_active_calls'):
                        active_call_ids = set(self.gateway._active_calls) if self.gateway._active_calls else set()
                    
                    # 各call_idの最終活動時刻をチェック
                    for call_id, last_activity_time in list(self.last_activity.items()):
                        # 【緊急修正】アクティブでない通話はスキップ
                        if active_call_ids and call_id not in active_call_ids:
                            self.logger.info(f"[ACTIVITY_MONITOR] Skipping inactive call: call_id={call_id}")
                            continue
                        
                        # 再生中は無音タイムアウトをスキップ
                        if self.is_playing.get(call_id, False):
                            continue
                        
                        elapsed = current_time - last_activity_time
                        if elapsed >= timeout_sec:
                            self.logger.info(
                                f"[ACTIVITY_MONITOR] Timeout detected: call_id={call_id} "
                                f"elapsed={elapsed:.1f}s -> calling FlowEngine.transition(NOT_HEARD)"
                            )
                            
                            # FlowEngine.transition("NOT_HEARD")を呼び出す
                            try:
                                flow_engine = self.flow_engines.get(call_id) or self.flow_engine
                                if flow_engine:
                                    state = self._get_session_state(call_id)
                                    client_id = self.call_client_map.get(call_id) or state.meta.get("client_id") or self.client_id or "000"
                                    
                                    # NOT_HEARDコンテキストで遷移
                                    context = {
                                        "intent": "NOT_HEARD",
                                        "text": "",
                                        "normalized_text": "",
                                        "keywords": self.keywords,
                                        "user_reply_received": False,
                                        "user_voice_detected": False,
                                        "timeout": True,
                                        "is_first_sales_call": getattr(state, "is_first_sales_call", False),
                                    }
                                    
                                    next_phase = flow_engine.transition(state.phase or "ENTRY", context)
                                    
                                    if next_phase != state.phase:
                                        state.phase = next_phase
                                        self.logger.info(
                                            f"[ACTIVITY_MONITOR] Phase transition: {state.phase} -> {next_phase} "
                                            f"(call_id={call_id}, timeout)"
                                        )
                                    
                                    # テンプレートを取得して再生
                                    template_ids = flow_engine.get_templates(next_phase)
                                    if template_ids:
                                        # 注意: last_activityの更新は再生成功時のみ行う（_handle_playback内で処理）
                                        # 再生失敗時は更新しないため、タイムアウトが継続的に発生しない
                                        self._play_template_sequence(call_id, template_ids, client_id)
                                        
                                        # NOT_HEARD (110) 再提示後、QAフェーズへ復帰を保証
                                        if next_phase == "NOT_HEARD" and "110" in template_ids:
                                            # 110再生後、自動的にQAフェーズへ遷移
                                            state.phase = "QA"
                                            self.logger.info(
                                                f"[ACTIVITY_MONITOR] NOT_HEARD (110) played, transitioning to QA: call_id={call_id}"
                                            )
                                            # runtime.logに出力
                                            runtime_logger = logging.getLogger("runtime")
                                            runtime_logger.info(f"[FLOW] call_id={call_id} phase=NOT_HEARD→QA intent=NOT_HEARD template=110 (timeout recovery)")
                            except Exception as e:
                                self.logger.exception(f"[ACTIVITY_MONITOR] Error handling timeout: {e}")
                except Exception as e:
                    if self._activity_monitor_running:
                        self.logger.exception(f"[ACTIVITY_MONITOR] Monitor thread error: {e}")
                    time.sleep(1.0)
        
        import threading
        self._activity_monitor_thread = threading.Thread(target=_activity_monitor_worker, daemon=True)
        self._activity_monitor_thread.start()
        self.logger.info("[ACTIVITY_MONITOR] Activity monitor thread started")
    
    def on_call_end(self, call_id: Optional[str], source: str = "unknown") -> None:
        """
        通話終了時の処理（明示的なクリーンアップ）
        
        :param call_id: 通話ID
        :param source: 呼び出し元（デバッグ用: "_complete_console_call" / "_handle_hangup" など）
        """
        if not call_id:
            return
        
        # 終了時点の状態を取得（ログ用）
        try:
            state = self._get_session_state(call_id)
            phase_at_end = state.phase
            # 【修正4】state.meta に client_id があればそれを使う（callごとにclientが変わる構成に対応）
            client_id_from_state = state.meta.get("client_id") if hasattr(state, 'meta') and state.meta else None
        except Exception:
            phase_at_end = "unknown"
            client_id_from_state = None
        # client_id の優先順位: state.meta > self.client_id > "000"
        effective_client_id = client_id_from_state or self.client_id or "000"
        
        # 【改善2・3】通話終了時のみフラグをクリア（再接続時の誤クリアを防ぐ）
        was_started = call_id in self._call_started_calls
        was_intro_played = call_id in self._intro_played_calls
        
        self._call_started_calls.discard(call_id)
        self._intro_played_calls.discard(call_id)
        
        # ACTIVITY_MONITOR用のlast_activityもクリア（タイムアウト処理停止）
        self.last_activity.pop(call_id, None)
        
        # 【緊急修正】古いセッションのデータを即座にクリーンアップ
        cleanup_items = [
            ('last_activity', self.last_activity),
            ('is_playing', self.is_playing),
            ('partial_transcripts', self.partial_transcripts),
            ('last_template_play', self.last_template_play),
        ]
        
        for name, data_dict in cleanup_items:
            if call_id in data_dict:
                del data_dict[call_id]
                self.logger.info(f"[CLEANUP] Removed {name} for call_id={call_id}")
        
        # ログ出力（デバッグ強化）
        self.logger.info(
            f"[AICORE] on_call_end() call_id={call_id} source={source} client_id={effective_client_id} "
            f"phase={phase_at_end} "
            f"_call_started_calls={was_started} _intro_played_calls={was_intro_played} -> cleared"
        )
        
        # 【セッションサマリー保存】セッション終了時にsummary.jsonを保存
        self._save_session_summary(call_id)
        
        # 【ASRストリーム停止】通話終了時にASRストリームを完全に停止
        try:
            self.reset_call(call_id)
            self.logger.info(f"[CLEANUP] reset_call() executed for call_id={call_id}")
        except Exception as e:
            self.logger.error(f"[CLEANUP] Failed to reset_call(): call_id={call_id} error={e}", exc_info=True)
        # 明示的に強制クリーンアップを呼び出して、残留データを確実に破棄する
        try:
            self.cleanup_call(call_id)
            self.logger.info(f"[CLEANUP] cleanup_call() executed for call_id={call_id}")
        except Exception as e:
            self.logger.debug(f"[CLEANUP] cleanup_call() failed for call_id={call_id}: {e}")

    def cleanup_asr_instance(self, call_id: str) -> None:
        """
        通話終了時に該当call_idのASRインスタンスをクリーンアップ
        【追加】通話ごとの独立ASRインスタンス管理用
        
        :param call_id: 通話ID
        """
        if not hasattr(self, 'asr_instances'):
            return
        
        if call_id in self.asr_instances:
            print(f"[ASR_CLEANUP_START] call_id={call_id}", flush=True)
            self.logger.info(f"[ASR_CLEANUP_START] call_id={call_id}")
            try:
                asr = self.asr_instances[call_id]
                # ASRストリームを停止
                if hasattr(asr, 'end_stream'):
                    asr.end_stream(call_id)
                elif hasattr(asr, 'stop'):
                    asr.stop()
                # インスタンスを削除
                del self.asr_instances[call_id]
                print(f"[ASR_CLEANUP_DONE] call_id={call_id}, remaining={len(self.asr_instances)}", flush=True)
                self.logger.info(f"[ASR_CLEANUP_DONE] call_id={call_id}, remaining={len(self.asr_instances)}")
            except Exception as e:
                self.logger.error(f"[ASR_CLEANUP_ERROR] call_id={call_id}: {e}", exc_info=True)
                print(f"[ASR_CLEANUP_ERROR] call_id={call_id}: {e}", flush=True)
        else:
            self.logger.debug(f"[ASR_CLEANUP_SKIP] No ASR instance for call_id={call_id}")

    def cleanup_call(self, call_id: str) -> None:
        """
        強制クリーンアップ: セッション関連の残留データやキューを明示的に破棄する
        通話開始時や終了時の冗長処理として呼び出すことを想定
        """
        try:
            # Basic session maps
            try:
                self._call_started_calls.discard(call_id)
            except Exception:
                pass
            try:
                self._intro_played_calls.discard(call_id)
            except Exception:
                pass

            # Clear common per-call dicts
            dict_names = [
                'last_activity', 'is_playing', 'partial_transcripts',
                'last_template_play', 'session_info', 'last_ai_templates'
            ]
            # 【追加】FreeSWITCH 側で再生中の音声を強制停止（uuid_break / uuid_kill）
            try:
                # 複数の候補フィールドをチェックして uuid を取得する（既存フィールド名に合わせて柔軟に取得）
                uuid = None
                try:
                    if hasattr(self, 'call_uuid_map') and isinstance(self.call_uuid_map, dict):
                        uuid = self.call_uuid_map.get(call_id) or uuid
                except Exception:
                    pass
                try:
                    if not uuid and hasattr(self, 'call_client_map') and isinstance(self.call_client_map, dict):
                        # 一部コードでは UUID を別マップで管理している可能性があるため保険的にチェック
                        uuid = getattr(self, 'call_uuid_by_call_id', {}).get(call_id) or uuid
                except Exception:
                    pass
                try:
                    if not uuid and hasattr(self, '_call_uuid_map') and isinstance(self._call_uuid_map, dict):
                        uuid = self._call_uuid_map.get(call_id) or uuid
                except Exception:
                    pass

                if uuid:
                    self.logger.info(f"[CLEANUP] Sending uuid_break/uuid_kill to FreeSWITCH for uuid={uuid} call_id={call_id}")
                    import subprocess
                    # Try a couple of common fs_cli paths
                    fs_cli_paths = ["/usr/local/freeswitch/bin/fs_cli", "/usr/bin/fs_cli", "/usr/local/bin/fs_cli"]
                    executed = False
                    for fs_cli in fs_cli_paths:
                        try:
                            # uuid_break で再生を停止（all は全チャネルへ影響）
                            subprocess.run([fs_cli, "-x", f"uuid_break {uuid} all"], timeout=2, capture_output=True)
                            # 念のため uuid_kill（必要なら通話自体を切断）
                            subprocess.run([fs_cli, "-x", f"uuid_kill {uuid}"], timeout=2, capture_output=True)
                            executed = True
                            self.logger.info(f"[CLEANUP] fs_cli executed at {fs_cli} for uuid={uuid}")
                            break
                        except FileNotFoundError:
                            continue
                        except Exception as e:
                            self.logger.warning(f"[CLEANUP] fs_cli call failed ({fs_cli}) for uuid={uuid}: {e}")
                    if not executed:
                        # 最後の手段: try generic shell command (may fail on restricted env)
                        try:
                            subprocess.run(["fs_cli", "-x", f"uuid_break {uuid} all"], timeout=2, capture_output=True)
                            subprocess.run(["fs_cli", "-x", f"uuid_kill {uuid}"], timeout=2, capture_output=True)
                            self.logger.info(f"[CLEANUP] fs_cli executed via PATH for uuid={uuid}")
                        except Exception as e:
                            self.logger.error(f"[CLEANUP] Could not execute fs_cli for uuid={uuid}: {e}")
            except Exception as e:
                self.logger.debug(f"[CLEANUP] FreeSWITCH stop attempt failed for call_id={call_id}: {e}")
            for name in dict_names:
                try:
                    d = getattr(self, name, None)
                    if isinstance(d, dict) and call_id in d:
                        del d[call_id]
                        self.logger.info(f"[CLEANUP] Removed {name} entry for call_id={call_id}")
                except Exception as e:
                    self.logger.debug(f"[CLEANUP] Could not remove {name} for {call_id}: {e}")

            # FlowEngine instances per-call
            try:
                if hasattr(self, 'flow_engines') and isinstance(self.flow_engines, dict):
                    if call_id in self.flow_engines:
                        del self.flow_engines[call_id]
                        self.logger.info(f"[CLEANUP] Removed flow_engine instance for call_id={call_id}")
            except Exception:
                pass

            # TTS / audio queues
            try:
                for qname in ('tts_queue', 'audio_output_queue', 'tts_out_queue'):
                    q = getattr(self, qname, None)
                    if q is not None:
                        try:
                            while not q.empty():
                                q.get_nowait()
                            self.logger.info(f"[CLEANUP] Cleared queue {qname} for call_id={call_id}")
                        except Exception:
                            self.logger.debug(f"[CLEANUP] Failed clearing queue {qname} for call_id={call_id}")
            except Exception:
                pass

            # ASR instance queues
            try:
                if hasattr(self, 'asr_instances') and isinstance(self.asr_instances, dict):
                    asr = self.asr_instances.get(call_id)
                    if asr:
                        if hasattr(asr, '_queue'):
                            try:
                                while not asr._queue.empty():
                                    asr._queue.get_nowait()
                                self.logger.info(f"[CLEANUP] Flushed ASR queue for {call_id}")
                            except Exception:
                                self.logger.debug(f"[CLEANUP] Failed flushing ASR queue for {call_id}")
                        # Attempt to stop ASR instance if stop/close method exists
                        try:
                            if hasattr(asr, 'stop'):
                                asr.stop()
                            elif hasattr(asr, 'close'):
                                asr.close()
                            self.logger.info(f"[CLEANUP] Stopped ASR instance for {call_id}")
                        except Exception:
                            self.logger.debug(f"[CLEANUP] Could not stop ASR instance for {call_id}")
                        # Finally remove reference
                        try:
                            del self.asr_instances[call_id]
                        except Exception:
                            pass
            except Exception:
                pass

            # Auto hangup timers
            try:
                if hasattr(self, '_auto_hangup_timers') and isinstance(self._auto_hangup_timers, dict):
                    t = self._auto_hangup_timers.pop(call_id, None)
                    if t is not None:
                        try:
                            t.cancel()
                        except Exception:
                            pass
                        self.logger.info(f"[CLEANUP] Cancelled auto_hangup timer for {call_id}")
            except Exception:
                pass

            # Reset call state via reset_call if available
            try:
                if hasattr(self, 'reset_call'):
                    self.reset_call(call_id)
                    self.logger.info(f"[CLEANUP] reset_call() invoked for call_id={call_id}")
            except Exception as e:
                self.logger.debug(f"[CLEANUP] reset_call error for {call_id}: {e}")
        except Exception as e:
            self.logger.exception(f"[CLEANUP] Unexpected error during cleanup_call for {call_id}: {e}")

    def _load_flow(self, client_id: str) -> dict:
        """
        クライアントごとの会話フローを読み込む
        
        :param client_id: クライアントID
        :return: 会話フロー設定（dict）
        """
        path = f"/opt/libertycall/config/clients/{client_id}/flow.json"
        default_path = "/opt/libertycall/config/system/default_flow.json"
        
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                flow = json.load(f)
                version = flow.get("version", "unknown")
                self.logger.info(f"[FLOW] client={client_id} version={version} loaded")
                return flow
        else:
            if os.path.exists(default_path):
                with open(default_path, "r", encoding="utf-8") as f:
                    flow = json.load(f)
                    self.logger.warning(f"[FLOW] client={client_id} missing, loaded default version={flow.get('version', 'unknown')}")
                    return flow
            else:
                self.logger.error(f"[FLOW] client={client_id} missing and default not found, using empty flow")
                return {}
    
    def _load_json(self, path: str, default: str = None) -> dict:
        """
        汎用JSON読み込みヘルパー
        
        :param path: JSONファイルのパス
        :param default: フォールバック用のデフォルトパス
        :return: JSONデータ（dict）
        """
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        elif default and os.path.exists(default):
            with open(default, "r", encoding="utf-8") as f:
                self.logger.debug(f"[FLOW] Using default file: {default}")
                return json.load(f)
        return {}
    
    def _load_keywords_from_config(self) -> None:
        """
        keywords.jsonからキーワードを読み込んでインスタンス変数に設定
        """
        if not self.keywords:
            self.logger.warning("[FLOW] keywords not loaded, using empty lists")
            self.AFTER_085_NEGATIVE_KEYWORDS = []
            self.ENTRY_TRIGGER_KEYWORDS = []
            self.CLOSING_YES_KEYWORDS = []
            self.CLOSING_NO_KEYWORDS = []
            return
        
        self.AFTER_085_NEGATIVE_KEYWORDS = self.keywords.get("AFTER_085_NEGATIVE_KEYWORDS", [])
        self.ENTRY_TRIGGER_KEYWORDS = self.keywords.get("ENTRY_TRIGGER_KEYWORDS", [])
        self.CLOSING_YES_KEYWORDS = self.keywords.get("CLOSING_YES_KEYWORDS", [])
        self.CLOSING_NO_KEYWORDS = self.keywords.get("CLOSING_NO_KEYWORDS", [])
        
        self.logger.debug(
            f"[FLOW] Keywords loaded: ENTRY_TRIGGER={len(self.ENTRY_TRIGGER_KEYWORDS)}, "
            f"CLOSING_YES={len(self.CLOSING_YES_KEYWORDS)}, CLOSING_NO={len(self.CLOSING_NO_KEYWORDS)}, "
            f"AFTER_085_NEGATIVE={len(self.AFTER_085_NEGATIVE_KEYWORDS)}"
        )
    
        
    def _save_transcript_event(self, call_id: str, text: str, is_final: bool, kwargs: dict) -> None:
        """
        on_transcriptイベントをtranscript.jsonlに保存（JSONL形式で逐次追記）
        ログエラー発生時でも音声再生を継続するように保護
        
        :param call_id: 通話UUID
        :param text: 認識されたテキスト
        :param is_final: 確定した発話かどうか
        :param kwargs: 追加パラメータ
        """
        try:
            client_id = getattr(self, "client_id", "000")
            save_transcript_event(call_id, text, is_final, kwargs, client_id)
            
            # セッション情報を更新（intent追跡用）
            if call_id not in self.session_info:
                self.session_info[call_id] = {
                    "start_time": datetime.now(),
                    "intents": [],
                    "phrases": [],
                }
            
            # finalの場合はintentを記録
            if is_final and text:
                session_info = self.session_info[call_id]
                session_info["phrases"].append({
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                })
            
            self.logger.debug(f"[SESSION_LOG] Saved transcript event: call_id={call_id} is_final={is_final}")
        except Exception as e:
            self.logger.exception(f"[SESSION_LOG] Failed to save transcript event: {e}")
    
    def _save_session_summary(self, call_id: str) -> None:
        """
        セッション終了時にsummary.jsonを保存
        
        :param call_id: 通話UUID
        """
        try:
            # セッション情報を取得
            session_info = self.session_info.get(call_id, {})
            state = self._get_session_state(call_id)
            client_id = self.call_client_map.get(call_id) or state.meta.get("client_id") or self.client_id or "000"
            
            # 開始時刻と終了時刻を取得
            start_time = session_info.get("start_time", datetime.now())
            end_time = datetime.now()
            
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            elif not isinstance(start_time, datetime):
                start_time = datetime.now()
            
            # intentリストを取得（phrasesから抽出）
            phrases = session_info.get("phrases", [])
            intents = []
            for phrase in phrases:
                # phraseからintentを抽出（既存のロジックを使用）
                text = phrase.get("text", "")
                if text:
                    normalized = normalize_text(text)
                    # Intent方式は廃止されました。UNKNOWNとして扱います
                    intent = "UNKNOWN"
                    if intent and intent not in intents:
                        intents.append(intent)
            
            # handoff_occurredを判定
            handoff_occurred = state.transfer_requested or state.handoff_completed or state.phase == "HANDOFF_DONE"
            
            # summary.jsonを作成
            summary = {
                "client_id": client_id,
                "uuid": call_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "total_phrases": len(phrases),
                "intents": intents,
                "handoff_occurred": handoff_occurred,
                "final_phase": state.phase or "UNKNOWN",
            }
            
            # summary.jsonを保存（モジュール関数を使用）
            save_session_summary(call_id, summary, client_id)
            
            self.logger.info(f"[SESSION_SUMMARY] Saved session summary: call_id={call_id} client_id={client_id}")
            
            # セッション情報をクリア（メモリ節約）
            self.session_info.pop(call_id, None)
        except Exception as e:
            self.logger.exception(f"[SESSION_SUMMARY] Failed to save session summary: {e}")
    
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
        texts: List[str] = []
        for template_id in template_ids:
            template_text = get_response_template(template_id)
            if template_text:
                texts.append(template_text)
        return " ".join(texts).strip()

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
        """
        通話ログを 1行追記する。
        形式: [YYYY-mm-dd HH:MM:SS] [caller] ROLE (tpl=XXX) text
        """
        try:
            call_id = getattr(self, "call_id", None)
            client_id = getattr(self, "client_id", "000")
            if not client_id:
                client_id = "000"
            
            # TMP_CALLやunknownの場合はログセッションIDを使用
            if not call_id or str(call_id).lower() in ("unknown", "temp_call"):
                if not getattr(self, "log_session_id", None):
                    now = datetime.now()
                    self.log_session_id = now.strftime("CALL_%Y%m%d_%H%M%S%f")
                call_id = self.log_session_id
            
            append_call_log(str(call_id), role, text, template_id, client_id)
            
        except Exception as e:
            # 予期せぬ例外もログには残すが、会話は止めない
            self.logger.exception(f"CALL_LOGGING_ERROR in _append_call_log: {e}")

    def _trigger_transfer(self, call_id: str) -> None:
        """
        転送をトリガーする（_generate_reply の末尾などから呼ばれる）
        
        注意: このメソッドは後方互換性のため残していますが、
        新しいコードでは _trigger_transfer_if_needed を使用してください。
        """
        self.logger.info("TRANSFER_TRIGGER_START: call_id=%s", call_id)
        if hasattr(self, "transfer_callback") and self.transfer_callback:
            try:
                self.logger.info("TRANSFER_TRIGGER: calling transfer_callback call_id=%s", call_id)
                self.transfer_callback(call_id)
                self.logger.info("TRANSFER_TRIGGER_DONE: transfer_callback completed call_id=%s", call_id)
            except Exception as exc:
                self.logger.exception("TRANSFER_TRIGGER_ERROR: transfer_callback error call_id=%s error=%r", call_id, exc)
        else:
            self.logger.warning("TRANSFER_TRIGGER_SKIP: transfer requested but no callback is set call_id=%s", call_id)

    def _trigger_transfer_if_needed(self, call_id: str, state: ConversationState) -> None:
        """
        transfer_requested / transfer_executed / handoff_state を見て、
        必要な場合のみ transfer_callback を 1 回だけ呼び出すヘルパー。
        
        このメソッドを通してのみ transfer_callback を実行する想定。
        既存挙動を変えないことを最優先とし、
        条件は現行コードに合わせて調整する。
        """
        if not getattr(self, "transfer_callback", None):
            return
        
        # すでに実行済みなら何もしない
        if state.transfer_executed:
            return
        
        # 転送要求が立っていないなら何もしない
        if not state.transfer_requested:
            return
        
        try:
            self.logger.info(
                "AICore: TRIGGER_TRANSFER call_id=%s phase=%s handoff_state=%s",
                call_id,
                state.phase,
                state.handoff_state,
            )
            self.transfer_callback(call_id)  # type: ignore[misc]
            state.transfer_executed = True
        except Exception:
            self.logger.exception(
                "AICore: transfer_callback failed call_id=%s", call_id
            )

    def _schedule_auto_hangup(self, call_id: str, delay_sec: float = 60.0) -> None:
        """
        END フェーズ遷移後の自動切断タイマーをセットする
        
        注意: 既存のタイマーがある場合は自動的にキャンセルしてから新しいタイマーをセットします。
        これにより、以下のシーケンスでも正しく動作します：
        1. _schedule_auto_hangup(call_id, 60.0) → timer起動
        2. 50秒後、ユーザーが「やっぱり話したい」と発話
        3. _generate_reply が再度 _schedule_auto_hangup を呼ぶ → 既存timerをキャンセル
        4. 新しいtimerが60秒でセット
        5. その10秒後、ユーザーが切断 → reset_call が呼ばれる → timerをキャンセル
        
        reset_call でも timer.cancel() を実行していますが、これは通話終了時のクリーンアップとして
        実行されるもので、_schedule_auto_hangup 内のキャンセル処理とは競合しません。
        """
        key = call_id or "GLOBAL_CALL"

        # ログ：入口
        self.logger.info(
            "AUTO_HANGUP_SCHEDULE_REQUEST: call_id=%s delay=%.1f hangup_cb=%s",
            key,
            delay_sec,
            "set" if self.hangup_callback else "none",
        )

        # callback 未設定なら何もしない
        if not self.hangup_callback:
            self.logger.warning(
                "AUTO_HANGUP_SKIP: call_id=%s reason=no_hangup_callback", key
            )
            return

        # 既存タイマーがあればキャンセル
        old_timer = self._auto_hangup_timers.get(key)
        if old_timer is not None:
            try:
                old_timer.cancel()
                self.logger.info(
                    "AUTO_HANGUP_CANCEL_PREV: call_id=%s", key
                )
            except Exception as e:
                self.logger.warning(
                    "AUTO_HANGUP_CANCEL_PREV_ERROR: call_id=%s error=%r",
                    key, e
                )

        def _do_hangup() -> None:
            self.logger.info(
                "AUTO_HANGUP_TRIGGER: call_id=%s", key
            )
            try:
                if self.hangup_callback:
                    self.hangup_callback(key)  # 実際の切断処理は gateway 側
            except Exception as e:
                self.logger.exception(
                    "AUTO_HANGUP_CALLBACK_ERROR: call_id=%s error=%r",
                    key, e
                )
            finally:
                # 実行後に辞書から消す
                try:
                    self._auto_hangup_timers.pop(key, None)
                except Exception:
                    pass

        t = threading.Timer(delay_sec, _do_hangup)
        t.daemon = True  # 念のため
        self._auto_hangup_timers[key] = t
        t.start()

        self.logger.info(
            "AUTO_HANGUP_SCHEDULED: call_id=%s delay=%.1f",
            key,
            delay_sec,
        )

    def on_call_start(self, call_id: str, client_id: str = None, **kwargs) -> None:
        """
        通話開始時の処理
        
        :param call_id: 通話ID
        :param client_id: クライアントID（省略時は self.client_id を使用）
        :param kwargs: その他の引数
        """
        # 【追加】開始イベントの連打防止（2秒以内の再呼び出しは無視）
        try:
            import time
            current_time = time.time()
            last_time = getattr(self, "last_start_times", {}).get(call_id, 0)
            if (current_time - last_time) < 2.0:
                # logger が存在する前提で警告を出す
                try:
                    self.logger.warning(f"[CALL_START] Ignored duplicate start event for {call_id}")
                except Exception:
                    print(f"[CALL_START] Ignored duplicate start event for {call_id}", flush=True)
                return
            # 時刻を更新して処理続行
            try:
                if not hasattr(self, "last_start_times"):
                    self.last_start_times = {}
                self.last_start_times[call_id] = current_time
            except Exception:
                pass
        except Exception:
            # 時刻取得等に失敗しても処理を続行する（保守性優先）
            pass

        effective_client_id = client_id or self.client_id or "000"
        
        # 【追加】既存セッションの強制クリーンアップ（ゾンビセッション対策）
        try:
            # Check common active-calls holders
            active_found = False
            if hasattr(self, 'active_calls') and call_id in getattr(self, 'active_calls') :
                active_found = True
            elif hasattr(self, 'gateway') and hasattr(self.gateway, '_active_calls') and call_id in getattr(self.gateway, '_active_calls'):
                active_found = True
            if active_found:
                self.logger.warning(f"[CLEANUP] Found existing active session for {call_id} at start. Forcing cleanup.")
                try:
                    self.cleanup_call(call_id)
                except Exception as e:
                    self.logger.exception(f"[CLEANUP] cleanup_call error for {call_id}: {e}")
        except Exception:
            # Non-fatal, continue startup
            pass

        # 【診断用】強制的に可視化（logger設定に依存しない）
        print(f"[DEBUG_PRINT] on_call_start called call_id={call_id} client_id={effective_client_id} self.client_id={self.client_id}", flush=True)
        
        # 【改善1】on_call_start() 自体の重複呼び出し防止（全クライアント共通）
        if call_id in self._call_started_calls:
            print(f"[DEBUG_PRINT] on_call_start=skipped call_id={call_id} reason=already_called", flush=True)
            self.logger.info(f"[AICORE] on_call_start=skipped call_id={call_id} reason=already_called")
            return
        
        print(f"[DEBUG_PRINT] on_call_start proceeding call_id={call_id} effective_client_id={effective_client_id}", flush=True)
        self.logger.info(f"[AICORE] on_call_start() call_id={call_id} client_id={effective_client_id}")
        # 呼び出し済みフラグを設定（001以外でも設定）
        self._call_started_calls.add(call_id)
        
        # 【最終チェック1】state.meta["client_id"] をセット（ログ用の一貫性確保）
        state = self._get_session_state(call_id)
        if not hasattr(state, 'meta') or state.meta is None:
            state.meta = {}
        state.meta["client_id"] = effective_client_id
        
        # クライアント001専用：録音告知＋LibertyCall挨拶を再生
        if effective_client_id == "001":
            print(f"[DEBUG_PRINT] client_id=001 detected, proceeding with intro template", flush=True)
            # 【改善1】001の場合だけ、phase を一旦 "INTRO" にしておく
            state = self._get_session_state(call_id)
            state.phase = "INTRO"
            self.logger.debug(f"[AICORE] Phase set to INTRO for call_id={call_id} (client_id=001, will change to ENTRY after intro)")
            # 【改善3】テンプレート存在チェックを緩和（解決は下層に任せる）
            # tts_callback が設定されている場合のみ実行
            if hasattr(self, 'tts_callback') and self.tts_callback:
                print(f"[DEBUG_PRINT] tts_callback is set, calling with template 000-002", flush=True)
                try:
                    print(f"[DEBUG_PRINT] intro=queued template_id=000-002 call_id={call_id}", flush=True)
                    self.logger.info(f"[AICORE] intro=queued template_id=000-002 call_id={call_id}")
                    try:
                        # 再生予定のテンプレテキストを記録（エコーフィルタ用）
                        try:
                            self.current_system_text = self._render_templates(["000-002"]) or ""
                        except Exception:
                            self.current_system_text = "000-002"
                    except Exception:
                        pass
                    self.tts_callback(call_id, None, ["000-002"], False)  # type: ignore[misc, attr-defined]
                    # 再生済みフラグを設定
                    self._intro_played_calls.add(call_id)
                    print(f"[DEBUG_PRINT] intro=sent template_id=000-002 call_id={call_id}", flush=True)
                    self.logger.info(f"[AICORE] intro=sent template_id=000-002 call_id={call_id}")
                    
                    # 【改善1】intro送信完了後、ENTRYフェーズへ遷移
                    state = self._get_session_state(call_id)
                    state.phase = "ENTRY"
                    self.logger.debug(f"[AICORE] Phase changed from INTRO to ENTRY for call_id={call_id} (after intro sent)")
                    
                    # 【改善2】intro送信完了
                    # 注意: ENTRYテンプレート（004/005）は既存の動作（on_transcript() でユーザー発話を受けた時）に任せる
                    # これにより、introが再生中にENTRYテンプレートが被ることを防ぐ
                    self.logger.debug(f"[AICORE] intro_sent entry_templates=deferred (will be sent by on_transcript when user speaks) call_id={call_id}")
                    
                except Exception as e:
                    self.logger.exception(f"[AICORE] intro=error template_id=000-002 call_id={call_id} error={e}")
                    # エラー時もENTRYフェーズへ遷移
                    state = self._get_session_state(call_id)
                    state.phase = "ENTRY"
            else:
                print(f"[DEBUG_PRINT] intro=error tts_callback not set call_id={call_id}", flush=True)
                self.logger.warning("[AICORE] intro=error tts_callback not set, cannot send template 000-002")
                # tts_callback未設定でもENTRYフェーズへ遷移
                state = self._get_session_state(call_id)
                state.phase = "ENTRY"
        else:
            # 001以外は即座にENTRYフェーズへ遷移（既存の動作）
            state = self._get_session_state(call_id)
            state.phase = "ENTRY"
            self.logger.debug(f"[AICORE] Phase set to ENTRY for call_id={call_id} (client_id={effective_client_id})")

    def _handle_entry_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        # Intent方式は廃止されました。dialogue_flow方式を使用
        # ノイズ・聞き取れないケースの処理（最優先）
        if "ゴニョゴニョ" in raw_text or len(raw_text.strip()) == 0:
            state.phase = "QA"
            state.last_intent = "NOT_HEARD"
            template_ids = ["0602"]  # 聞き取れない場合のテンプレート
            return "NOT_HEARD", template_ids, False
        # 挨拶判定
        if any(kw in raw_text.lower() for kw in ["もしもし", "こんにちは", "おはよう"]):
            state.phase = "QA"
            state.last_intent = "GREETING"
            return "GREETING", ["004"], False
        if self._contains_keywords(normalized_text, self.ENTRY_TRIGGER_KEYWORDS):
            state.phase = "ENTRY_CONFIRM"
            state.last_intent = "INQUIRY"
            return "INQUIRY", ["006"], False
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_qa_phase(
        self,
        call_id: str,
        raw_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        通常QAフェーズ + HANDOFF導入フェーズ。
        戻り値: (intent, template_ids, transfer_requested)
        """
        # Intent方式は廃止されました。dialogue_flow方式を使用
        intent = "UNKNOWN"
        handoff_state = state.handoff_state
        transfer_requested = state.transfer_requested
        
        # --------------------------------------------------
        # すでに handoff 完了済み → 0604/104 は二度と出さない
        # --------------------------------------------------
        if handoff_state == "done":
            # Intent方式は廃止されました。デフォルト応答
            template_ids = ["114"]  # デフォルト応答
            # 念のため 0604/104 を強制フィルタ
            template_ids = [tid for tid in template_ids if tid not in ("0604", "104")]
            if intent == "SALES_CALL":
                last_intent = state.last_intent
                if last_intent == "SALES_CALL":
                    state.phase = "END"
                else:
                    state.phase = "AFTER_085"
            elif intent == "END_CALL":
                state.phase = "END"
            else:
                state.phase = "AFTER_085"
            state.last_intent = intent
            return intent, template_ids, transfer_requested
        
        # --------------------------------------------------
        # handoff_state == "confirming" の処理は別関数で扱う想定
        # （_generate_reply から _handle_handoff_confirm を呼ぶ）
        # --------------------------------------------------
        
        # --------------------------------------------------
        # 通常QA: intent_rules に任せるが、0604/104 はこのフェーズでは使わない想定
        # --------------------------------------------------
        # Intent方式は廃止されました。dialogue_flow方式を使用
        # 温度の低いリード（INQUIRY_PASSIVE）の処理は削除
        # デフォルト応答
        template_ids = ["114"]  # デフォルト応答
        if intent == "SALES_CALL":
            last_intent = state.last_intent
            if last_intent == "SALES_CALL":
                state.phase = "END"
            else:
                state.phase = "AFTER_085"
        elif intent == "END_CALL":
            state.phase = "END"
        else:
            state.phase = "AFTER_085"
        state.last_intent = intent
        return intent, template_ids, transfer_requested

    def _handle_after_085_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        # Intent方式は廃止されました。dialogue_flow方式を使用
        intent = "UNKNOWN"
        
        # 【修正】HANDOFF_REQUEST は phase に関係なく、常に 0604 を返す
        # handoff_state == "done" の状態でも「担当者お願いします」と言われたら、再度確認文を返す
        # handoff_state が idle または done の場合のみ処理（confirming 中は既存のハンドオフ確認フローに任せる）
        # 念のため、handoff_state が未設定の場合は "idle" をデフォルト値として使用
        # ハンドオフ要求の簡易判定
        handoff_keywords = ["担当者", "人間", "代わって", "つないで", "オペレーター"]
        if any(kw in raw_text for kw in handoff_keywords) and state.handoff_state in ("idle", "done"):
            intent = "HANDOFF_REQUEST"
            state.handoff_state = "confirming"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = True
            state.transfer_requested = False
            state.transfer_executed = False
            template_ids = ["0604"]
            state.last_intent = intent
            return intent, template_ids, False
        
        # 営業電話判定（簡易版）
        if "営業" in raw_text:
            intent = "SALES_CALL"
            last_intent = state.last_intent
            if last_intent == "SALES_CALL":
                # 2回目の営業電話発話（「はい営業です」など）の場合は END に移行
                state.phase = "END"
                template_ids = ["094", "088"]  # 営業電話用テンプレート
                # handoff_state == "done" の場合は 0604/104 を出さない
                if state.handoff_state == "done":
                    template_ids = [tid for tid in template_ids if tid not in ["0604", "104"]]
                state.last_intent = intent
                return intent, template_ids, False
        
        if self._contains_keywords(normalized_text, self.AFTER_085_NEGATIVE_KEYWORDS):
            state.phase = "CLOSING"
            return "END_CALL", ["013"], False
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_entry_confirm_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        if self._contains_keywords(normalized_text, self.CLOSING_YES_KEYWORDS):
            state.phase = "QA"
            state.last_intent = "INQUIRY"
            return "INQUIRY", ["010"], False
        if self._contains_keywords(normalized_text, self.CLOSING_NO_KEYWORDS):
            state.phase = "END"
            state.last_intent = "END_CALL"
            return "END_CALL", ["087", "088"], False
        # ユーザー返答がある場合はQAへ、ない場合はWAITINGへ
        # 注意: 実際のWAITING処理はrealtime_gateway.py側でTTS送信後の待機として実装
        # ここでは、テンプレート006にwait_time_afterが設定されていることを前提にQAへ遷移
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)
    
    def _handle_waiting_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        WAITINGフェーズ: ユーザー返答待ち（1.5〜2.0秒待機）
        実際の待機処理はrealtime_gateway.py側で実装
        """
        # ユーザー音声が検知された場合はQAへ
        if raw_text and len(raw_text.strip()) > 0:
            state.phase = "QA"
            return self._handle_qa_phase(call_id, raw_text, state)
        # 返答なしの場合はNOT_HEARDへ
        state.phase = "NOT_HEARD"
        return "NOT_HEARD", ["110"], False
    
    def _handle_not_heard_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        NOT_HEARDフェーズ: 聞き取れなかった場合
        """
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_closing_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        if self._contains_keywords(normalized_text, self.CLOSING_YES_KEYWORDS):
            state.phase = "HANDOFF"
            state.last_intent = "SETUP"
            return "SETUP", ["060", "061", "062", "104"], False
        if self._contains_keywords(normalized_text, self.CLOSING_NO_KEYWORDS):
            state.phase = "END"
            state.last_intent = "END_CALL"
            return "END_CALL", ["087", "088"], False
        state.phase = "QA"
        return self._handle_qa_phase(call_id, raw_text, state)

    def _handle_handoff_confirm(
        self,
        call_id: str,
        raw_text: str,
        intent: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], str, bool]:
        """
        HANDOFF 確認時のラッパー。
        実際の判定ロジックは HandoffStateMachine に委譲する。
        """
        from .text_utils import normalize_text
        
        # Intent方式は削除されました。intent が UNKNOWN の場合はそのまま使用
        # HandoffStateMachine 内で適切に処理されます
        
        normalized = normalize_text(raw_text)
        
        def contains_no_keywords(text: str) -> bool:
            # 既存の self._contains_keywords(normalized, self.CLOSING_NO_KEYWORDS) を包むヘルパ
            return self._contains_keywords(text, self.CLOSING_NO_KEYWORDS)
        
        template_ids, result_intent, transfer_requested, updated_raw = (
            self._handoff_sm.handle_confirm(
                call_id=call_id,
                raw_text=raw_text,
                intent=intent,
                state=state.raw,
                contains_no_keywords=lambda text=normalized: contains_no_keywords(text),
            )
        )
        
        # updated_raw は state.raw と同じ参照なので、state をそのまま使う
        updated_state = state
        
        # テンプレートレンダリング
        reply_text = self._render_templates(template_ids)
        
        # 転送コールバックの実行は on_transcript 内で TTS 送信後に実行される
        # （transfer_requested フラグを on_transcript に渡し、_send_tts 内でTTS送信完了後に転送処理を開始）
        # transfer_requested は HandoffStateMachine で既に設定されている
        if result_intent in ("HANDOFF_YES", "HANDOFF_FALLBACK_YES"):
            # handoff_state が done に遷移したときに unclear_streak をリセット
            self._mis_guard.reset_unclear_streak_on_handoff_done(call_id, updated_state)
            # _trigger_transfer_if_needed は on_transcript 内で TTS 送信後に実行されるため、ここでは呼ばない
        
        # 自動切断予約（HANDOFF_NO の場合）
        if result_intent == "HANDOFF_NO":
            key = call_id or "GLOBAL_CALL"
            if self.hangup_callback:
                self.logger.info(
                    "AUTO_HANGUP_DIRECT_SCHEDULE: call_id=%s delay=60.0",
                    key,
                )
                try:
                    self._schedule_auto_hangup(key, delay_sec=60.0)
                except Exception as e:
                    self.logger.exception(
                        "AUTO_HANGUP_DIRECT_SCHEDULE_ERROR: call_id=%s error=%r",
                        key, e
                    )
            else:
                self.logger.warning(
                    "AUTO_HANGUP_DIRECT_SKIP: call_id=%s reason=no_hangup_callback",
                    key,
                )
        
        # state.raw は既に self.session_states[key] を参照しているため、明示的な代入は不要
        
        return reply_text, template_ids, result_intent, transfer_requested

    def _handle_handoff_phase(
        self,
        call_id: str,
        raw_text: str,
        normalized_text: str,
        state: ConversationState,
    ) -> Tuple[str, List[str], bool]:
        """
        Wrapper while confirming handoff (HANDOFF_CONFIRM_WAIT phase).
        Actual decision logic is delegated to _handle_handoff_confirm.
        """
        # Intent方式は削除されました。UNKNOWNとして処理
        intent = "UNKNOWN"
        reply_text, template_ids, result_intent, transfer_requested = self._handle_handoff_confirm(
            call_id, raw_text, intent, state
        )
        
        if result_intent == "HANDOFF_YES":
            state.phase = "HANDOFF_DONE"
            state.last_intent = "HANDOFF_YES"
            state.handoff_completed = True
            state.transfer_requested = True
            # handoff_state が done に遷移したときに unclear_streak をリセット
            self._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)
            # _trigger_transfer_if_needed は on_transcript 内で TTS 送信後に実行されるため、ここでは呼ばない
        elif result_intent == "HANDOFF_FALLBACK_YES":
            # 【追加】安全側に倒して有人へ繋ぐ場合
            state.phase = "HANDOFF_DONE"
            state.last_intent = "HANDOFF_YES"
            state.handoff_completed = True
            state.transfer_requested = True
            # handoff_state が done に遷移したときに unclear_streak をリセット
            self._mis_guard.reset_unclear_streak_on_handoff_done(call_id, state)
            # _trigger_transfer_if_needed は on_transcript 内で TTS 送信後に実行されるため、ここでは呼ばない
        elif result_intent in ("HANDOFF_NO", "HANDOFF_FALLBACK_NO"):
            state.phase = "END"
            state.last_intent = "END_CALL"
            state.handoff_completed = True
        else:
            state.phase = "HANDOFF_CONFIRM_WAIT"
            state.last_intent = "HANDOFF_REQUEST"
        
        # state.raw は既に self.session_states[key] を参照しているため、明示的な代入は不要
        return result_intent, template_ids, transfer_requested

    def _run_conversation_flow(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[List[str], str, bool]:
        state = self._get_session_state(call_id)
        normalized = normalize_text(raw_text)
        phase = state.phase
        intent = "UNKNOWN"
        template_ids: List[str] = []
        transfer_requested = False

        if phase == "END":
            return [], "END_CALL", False
        if phase == "INTRO":
            # INTROフェーズ中は何も返さない（intro再生中）
            self.logger.debug(f"[AICORE] Phase=INTRO, skipping response (intro playing) call_id={call_id}")
            return [], "UNKNOWN", False
        if phase == "ENTRY":
            intent, template_ids, transfer_requested = self._handle_entry_phase(call_id, raw_text, normalized, state)
        elif phase == "ENTRY_CONFIRM":
            intent, template_ids, transfer_requested = self._handle_entry_confirm_phase(call_id, raw_text, normalized, state)
        elif phase == "WAITING":
            intent, template_ids, transfer_requested = self._handle_waiting_phase(call_id, raw_text, normalized, state)
        elif phase == "NOT_HEARD":
            intent, template_ids, transfer_requested = self._handle_not_heard_phase(call_id, raw_text, normalized, state)
        elif phase == "QA":
            intent, template_ids, transfer_requested = self._handle_qa_phase(call_id, raw_text, state)
        elif phase == "AFTER_085":
            intent, template_ids, transfer_requested = self._handle_after_085_phase(call_id, raw_text, normalized, state)
        elif phase == "CLOSING":
            intent, template_ids, transfer_requested = self._handle_closing_phase(call_id, raw_text, normalized, state)
        elif phase == "HANDOFF" or phase == "HANDOFF_CONFIRM_WAIT":
            intent, template_ids, transfer_requested = self._handle_handoff_phase(call_id, raw_text, normalized, state)
        else:
            state.phase = "QA"
            intent, template_ids, transfer_requested = self._handle_qa_phase(call_id, raw_text, state)

        if not template_ids and state.phase != "END":
            intent = intent or "UNKNOWN"
            # 無言を絶対出さないフォールバック
            template_ids = ["110"]
        
        # 直前のAIテンプレートをstateに保存（HANDOFF判定用）
        state.last_ai_templates = template_ids
        
        return template_ids, intent, transfer_requested

    def _generate_reply(
        self,
        call_id: str,
        raw_text: str,
    ) -> Tuple[str, List[str], str, bool]:
        """
        Core conversation flow entry point.
        - dialogue_flow方式で応答を生成
        - HANDOFF state (idle / confirming / done)
        - normal template selection
        """
        state = self._get_session_state(call_id)
        handoff_state = state.handoff_state
        transfer_requested = state.transfer_requested
        
        # ========================================
        # 対話フロー方式を試す（フェーズ1: 料金のみ）
        # ========================================
        dialogue_templates = None
        try:
            # handoff_stateが"confirming"の場合はdialogue_flowをスキップ
            # （ハンドオフ確認中の応答はIntent方式で処理）
            if handoff_state != "confirming":
                dialogue_templates, dialogue_phase, dialogue_state = dialogue_get_response(
                    user_text=raw_text,
                    current_phase=state.phase,
                    state={
                        "silence_count": getattr(state, "silence_count", 0),
                        "waiting_retry_count": getattr(state, "waiting_retry_count", 0),
                    }
                )
                
                if dialogue_templates and len(dialogue_templates) > 0:
                    # 対話フロー方式で応答が見つかった
                    self.logger.info(
                        f"DIALOGUE_FLOW使用: call_id={call_id}, "
                        f"templates={dialogue_templates}, "
                        f"phase={state.phase}->{dialogue_phase}"
                    )
                    
                    # Phase更新
                    state.phase = dialogue_phase
                    
                    # State更新
                    for key, value in dialogue_state.items():
                        setattr(state, key, value)
                    
                    # template_idsを設定
                    template_ids = dialogue_templates
                    intent = "DIALOGUE_FLOW"  # ログ用
                    
                    # テンプレートレンダリング
                    reply_text = self._render_templates(template_ids)
                    state.last_intent = intent
                    return reply_text, template_ids, intent, False
                    
        except Exception as e:
            self.logger.error(f"DIALOGUE_FLOW エラー: call_id={call_id}, error={e}", exc_info=True)
            # エラーの場合は、通常のIntent方式にフォールバック
            dialogue_templates = None
        
        # ========================================
        # 対話フロー方式で応答が見つからなければ、デフォルト応答
        # ========================================
        
        # dialogue_flowで応答が見つからなかった場合のデフォルト処理
        self.logger.warning(f"DIALOGUE_FLOW未対応: call_id={call_id}, text='{raw_text}', handoff_state={handoff_state}")
        
        # handoff_state == "confirming" の場合は、ハンドオフ確認処理に委譲
        if handoff_state == "confirming":
            # ハンドオフ確認中の応答は _handle_handoff_confirm で処理
            # ここでは intent を "UNKNOWN" として設定（後続処理で適切に処理される）
            intent = "UNKNOWN"
        else:
            # 通常の場合はデフォルト応答
            intent = "UNKNOWN"
            template_ids = ["114"]  # "ご要件をもう一度お願いできますでしょうか？"
            reply_text = self._render_templates(template_ids)
            state.last_intent = intent
            return reply_text, template_ids, intent, False
        
        # 【新規】担当者不在時は 0605 でAI継続を案内
        if intent == "HANDOFF_REQUEST" and not getattr(self, "transfer_callback", None):
            self.logger.warning(
                "[HANDOFF_UNAVAILABLE] call_id=%s intent=%s transfer_callback=missing",
                call_id or "GLOBAL_CALL",
                intent,
            )
            state.handoff_state = "idle"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = False
            state.transfer_requested = False
            state.transfer_executed = False
            state.phase = "QA"
            # 0605: 担当者不在→AI継続案内
            template_ids = ["0605"]
            # 代替案を提示するためのメタ情報を設定（後続フローで参照可能に）
            state.meta["handoff_unavailable"] = True
            state.meta["handoff_alternative_offered"] = True
            reply_text = self._render_templates(template_ids)
            state.last_intent = "INQUIRY"
            return reply_text, template_ids, "HANDOFF_UNAVAILABLE", False

        # HANDOFF already completed → never output 0604/104 again
        if handoff_state == "done" and not state.transfer_requested:
            template_ids, base_intent, transfer_requested = self._run_conversation_flow(call_id, raw_text)
            template_ids = [tid for tid in template_ids if tid not in ("0604", "104")]
            reply_text = self._render_templates(template_ids)
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                base_intent,
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, base_intent, transfer_requested
        
        # HANDOFF confirming → delegate to dedicated handler
        if handoff_state == "confirming":
            reply_text, template_ids, result_intent, transfer_requested = self._handle_handoff_confirm(
                call_id, raw_text, intent, state
            )
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                result_intent,
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, result_intent, transfer_requested
        
        # Not in HANDOFF yet: first UNKNOWN → propose handoff with 0604 only (once per call)
        if intent == "UNKNOWN" and handoff_state == "idle" and not state.handoff_prompt_sent:
            state.handoff_state = "confirming"
            state.handoff_retry_count = 0
            state.handoff_prompt_sent = True
            state.transfer_requested = False
            template_ids = ["0604"]
            reply_text = self._render_templates(template_ids)
            # 【追加】最終決定直前のログ（DEBUGレベルに変更）
            self.logger.debug(
                "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
                call_id or "GLOBAL_CALL",
                intent,
                "UNKNOWN",
                template_ids,
                state.phase,
                state.handoff_state,
                state.not_heard_streak,
            )
            return reply_text, template_ids, "UNKNOWN", False
        
        # Normal QA flow
        template_ids, base_intent, transfer_requested = self._run_conversation_flow(call_id, raw_text)
        # If both 0604 and 104 are present, keep 0604 and drop 104
        # (do not speak both in the same turn)
        if "0604" in template_ids and "104" in template_ids:
            template_ids = [tid for tid in template_ids if tid != "104"]
        
        # 【修正理由】フォールバック処理の前にストリーク処理を実行すると、
        # フォールバックで ["110"] が設定された場合にストリークが正しく動作しない
        # そのため、フォールバック処理の後にストリーク処理を実行する必要がある
        # しかし、_run_conversation_flow 内でフォールバックが実行されるため、
        # ここでストリーク処理を実行する前に、template_ids が ["110"] かどうかを確認する
        
        # 「もう一度お願いします（110）」の連発を監視して、2回目で 0604 に切り替える
        key = call_id or "GLOBAL_CALL"
        
        # not_heard_streak の処理（MisunderstandingGuard に委譲）
        template_ids, intent, should_return_early = self._mis_guard.handle_not_heard_streak(
            call_id, state, template_ids, intent, base_intent
        )
        if should_return_early:
            # 0604 に切り替えた場合、reply_text を再生成する必要がある
            reply_text = self._render_templates(template_ids)
            return reply_text, template_ids, base_intent, transfer_requested
        
        # unclear_streak の処理（MisunderstandingGuard に委譲）
        self._mis_guard.handle_unclear_streak(call_id, state, template_ids)
        
        # --- 修正版: 「質問に答えたあと」に085を追加する ---
        # ユーザー質問直後ではなく、
        # AIが質問に回答した後（回答テンプレートが選択された時）に085を追加するよう修正。
        # これにより、自然なQA対話になる。
        # 質問intent（ユーザーが質問したintent）
        question_intents = [
            "PRICE", "SYSTEM_INQUIRY", "FUNCTION", "SUPPORT",
            "AI_IDENTITY", "SYSTEM_EXPLAIN", "RESERVATION",
            "MULTI_STORE", "DIALECT", "CALLBACK_REQUEST",
            "SETUP_DIFFICULTY", "AI_CALL_TOPIC", "SETUP"
        ]
        # 回答テンプレート（質問に対する回答として使われるテンプレートID）
        answer_templates = [
            "040", "041", "042", "043", "044", "045", "046", "047", "048", "049",  # 料金関連
            "020", "021", "022", "023", "023_AI_IDENTITY", "024", "025", "026",  # システム関連
            "060", "061", "062", "063", "064", "065", "066", "067", "068", "069",  # 機能・設定関連
            "070", "071", "072",  # 予約関連
            "0600", "0601", "0603",  # その他回答テンプレート
            "0280", "0281", "0282", "0283", "0284", "0285",  # 導入実績・サポート関連
        ]
        
        # 質問intentで、回答テンプレートが選択されている場合に085を追加
        if (base_intent in question_intents
            and "085" not in template_ids
            and state.phase != "AFTER_085"
            and base_intent not in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO", "END_CALL")
            and template_ids
            and any(tid in answer_templates for tid in template_ids)):
            # 回答テンプレートの直後にフォローアップとして085を出す
            template_ids.append("085")
            state.phase = "AFTER_085"
            self.logger.debug(
                "[NLG_DEBUG] Added 085 after answer intent: call_id=%s intent=%s tpl=%s phase=%s",
                call_id or "GLOBAL_CALL",
                base_intent,
                template_ids,
                state.phase,
            )
        
        reply_text = self._render_templates(template_ids)
        
        # ★ 086/087 を選んだ時点で必ず自動切断予約（転送しない場合のクローズ用）
        if "086" in template_ids and "087" in template_ids:
            if self.hangup_callback:
                # 強制テスト用: 環境変数で即座に切断をテストできる
                force_immediate_hangup = os.getenv("LC_FORCE_IMMEDIATE_HANGUP", "0") == "1"
                if force_immediate_hangup:
                    # タイマーを使わず、即座に hangup_callback を呼ぶ（デバッグ用）
                    self.logger.info(
                        "DEBUG_FORCE_HANGUP: call_id=%s (immediate, no timer)",
                        key,
                    )
                    try:
                        self.hangup_callback(key)
                    except Exception as e:
                        self.logger.exception(
                            "DEBUG_FORCE_HANGUP_ERROR: call_id=%s error=%r",
                            key, e
                        )
                else:
                    # 通常モード: 60秒後に自動切断
                    self.logger.info(
                        "AUTO_HANGUP_DIRECT_SCHEDULE: call_id=%s delay=60.0",
                        key,
                    )
                    try:
                        self._schedule_auto_hangup(key, delay_sec=60.0)
                    except Exception as e:
                        self.logger.exception(
                            "AUTO_HANGUP_DIRECT_SCHEDULE_ERROR: call_id=%s error=%r",
                            key, e
                        )
            else:
                self.logger.warning(
                    "AUTO_HANGUP_DIRECT_SKIP: call_id=%s reason=no_hangup_callback",
                    key,
                )
        
        # 【追加】最終決定直前のログ（DEBUGレベルに変更）
        self.logger.debug(
            "[NLG_DEBUG] call_id=%s intent=%s base_intent=%s tpl=%s phase=%s handoff_state=%s not_heard_streak=%s",
            call_id or "GLOBAL_CALL",
            intent,
            base_intent,
            template_ids,
            state.phase,
            state.handoff_state,
            state.not_heard_streak,
        )
        
        # GENERATE_REPLY_EXIT ログ（_generate_reply の出口を確認用）
        self.logger.info(
            "GENERATE_REPLY_EXIT: call_id=%s intent=%s base_intent=%s tpl=%s phase=%s has_086_087=%s",
            call_id or "GLOBAL_CALL",
            intent,
            base_intent,
            template_ids,
            state.phase,
            "086" in template_ids and "087" in template_ids,
        )
        
        return reply_text, template_ids, base_intent, transfer_requested

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
        """
        ストリーミングモード: 新しい音声チャンクをASRにfeedする。
        【修正】通話ごとに独立したASRインスタンスを使用（混線防止）
        
        :param call_id: 通話ID
        :param pcm16k_bytes: 16kHz PCM音声データ
        """
        # 受信ログ（デバッグレベル）
        self.logger.debug(f"[AI_CORE] on_new_audio called. Len={len(pcm16k_bytes)} call_id={call_id}")
        
        if not self.streaming_enabled:
            return
        
        # 通話が既に終了している場合は処理をスキップ（ゾンビ化防止）
        # 【修正】未登録ならリカバリ登録を行ってから処理を続行
        if call_id not in self._call_started_calls:
            self.logger.warning(f"[ASR_RECOVERY] call_id={call_id} not in _call_started_calls but receiving audio. Auto-registering.")
            self._call_started_calls.add(call_id)
            # return はしない！そのまま処理を続行させる
        
        # GoogleASR の場合は通話ごとの独立したASRインスタンスを使用
        if self.asr_provider == "google":
            self.logger.debug(f"AICore: on_new_audio (provider=google) call_id={call_id} len={len(pcm16k_bytes)} bytes")
            
            # 【修正】遅延初期化（古いプロセスとの互換性）
            if not hasattr(self, 'asr_instances'):
                self.asr_instances = {}
                self.asr_lock = threading.Lock()
                self._phrase_hints = []
                print(f"[ASR_INSTANCES_LAZY_INIT] asr_instances and lock created (lazy)", flush=True)
            
            # 【修正】スレッドセーフにASRインスタンスを取得または作成
            asr_instance = None
            newly_created = False
            with self.asr_lock:
                # === 追加：ロック取得時の状態をログ ===
                print(f"[ASR_LOCK_ACQUIRED] call_id={call_id}, current_instances={list(self.asr_instances.keys())}", flush=True)
                
                if call_id not in self.asr_instances:
                    import traceback
                    caller_stack = traceback.extract_stack()
                    caller_info = f"{caller_stack[-3].filename}:{caller_stack[-3].lineno} in {caller_stack[-3].name}"
                    print(f"[ASR_INSTANCE_CREATE] Creating new GoogleASR for call_id={call_id}", flush=True)
                    print(f"[ASR_CREATE_CALLER] call_id={call_id}, caller={caller_info}", flush=True)
                    self.logger.info(f"[ASR_INSTANCE_CREATE] Creating new GoogleASR for call_id={call_id}")
                    try:
                        new_asr = GoogleASR(
                            language_code="ja",
                            sample_rate=16000,
                            phrase_hints=getattr(self, '_phrase_hints', []),
                            ai_core=self,
                            error_callback=self._on_asr_error,
                        )
                        self.asr_instances[call_id] = new_asr
                        newly_created = True
                        print(f"[ASR_INSTANCE_CREATED] call_id={call_id}, total_instances={len(self.asr_instances)}", flush=True)
                        self.logger.info(f"[ASR_INSTANCE_CREATED] call_id={call_id}, total_instances={len(self.asr_instances)}")
                    except Exception as e:
                        self.logger.error(f"[ASR_INSTANCE_CREATE_FAILED] call_id={call_id}: {e}", exc_info=True)
                        print(f"[ASR_INSTANCE_CREATE_FAILED] call_id={call_id}: {e}", flush=True)
                        return
                else:
                    # === 追加：既存インスタンス再利用時のログ ===
                    print(f"[ASR_INSTANCE_REUSE] call_id={call_id} already exists", flush=True)
                # ロック内でインスタンスを取得
                asr_instance = self.asr_instances.get(call_id)
            
            # 【追加】新規作成時はストリームスレッド開始を待機（最大500ms）
            if newly_created and asr_instance is not None:
                # 明示的にストリームワーカーを起動
                asr_instance._start_stream_worker(call_id)
                max_wait = 0.5  # 最大500ms待機
                wait_interval = 0.02  # 20msごとにチェック
                elapsed = 0.0
                print(f"[ASR_STREAM_WAIT] call_id={call_id} Waiting for stream thread to start...", flush=True)
                while elapsed < max_wait:
                    if asr_instance._stream_thread is not None and asr_instance._stream_thread.is_alive():
                        break
                    time.sleep(wait_interval)
                    elapsed += wait_interval
                
                stream_ready = (asr_instance._stream_thread is not None and asr_instance._stream_thread.is_alive())
                if stream_ready:
                    print(f"[ASR_STREAM_READY] call_id={call_id} Stream thread ready after {elapsed:.3f}s", flush=True)
                    self.logger.info(f"[ASR_STREAM_READY] call_id={call_id} Stream thread ready after {elapsed:.3f}s")
                else:
                    print(f"[ASR_STREAM_TIMEOUT] call_id={call_id} Stream thread not ready after {elapsed:.3f}s", flush=True)
                    self.logger.warning(f"[ASR_STREAM_TIMEOUT] call_id={call_id} Stream thread not ready after {elapsed:.3f}s")
            
            # ロック外で音声をフィード（ASR処理をブロックしないため）
            if asr_instance is not None:
                try:
                    self.logger.warning(f"[ON_NEW_AUDIO_FEED] About to call feed_audio for call_id={call_id}, chunk_size={len(pcm16k_bytes)}")
                    asr_instance.feed_audio(call_id, pcm16k_bytes)
                    self.logger.warning(f"[ON_NEW_AUDIO_FEED_DONE] feed_audio completed for call_id={call_id}")
                except Exception as e:
                    self.logger.error(f"AICore: GoogleASR.feed_audio 失敗 (call_id={call_id}): {e}", exc_info=True)
                    self.logger.info(f"ASR_GOOGLE_ERROR: feed_audio失敗 (call_id={call_id}): {e}")
        else:
            # Whisper の場合
            self.asr_model.feed(call_id, pcm16k_bytes)  # type: ignore[union-attr]

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
        """
        ストリーミングモード: 確定した発話テキストを受け取り、AIロジックを実行して返答を生成する
        
        :param call_id: 通話ID
        :param text: 認識されたテキスト
        :param is_final: 確定した発話かどうか（デフォルト: True）
        :return: 返答テキスト（TTS に渡す）
        
        重要: partial（is_final=False）の場合は partial_transcripts に追記するだけ。
        会話ロジック（intent判定、テンプレート選択、ログ書き込みなど）は final（is_final=True）のときだけ実行される。
        """
        # 入口ログを簡素化
        if is_final:
            self.logger.info(f"[ASR_TRANSCRIPT] call_id={call_id} is_final=True text={text!r}")
        else:
            self.logger.debug(f"[ASR_TRANSCRIPT] call_id={call_id} is_final=False text={text!r}")

        # 【追加】トランスクリプト受信時の詳細ログ（デバッグ目的）
        try:
            text_preview = text if isinstance(text, str) else repr(text)
        except Exception:
            text_preview = "<unrepresentable>"
        self.logger.info(f"[TRANSCRIPT_DEBUG] Received text={text_preview!r}, is_final={is_final} for call_id={call_id}")

        # 再生中フラグが立っていなければ保持中の system_text をクリア（古い値の誤検出を防ぐ）
        try:
            playing = False
            if hasattr(self, 'is_playing') and isinstance(self.is_playing, dict):
                playing = bool(self.is_playing.get(call_id, False))
            if not playing and self.current_system_text:
                # clear stale system text
                self.current_system_text = ""
        except Exception:
            pass

        # 【追加】自己発話（システム再生のエコー）フィルタ
        try:
            if self.current_system_text:
                import re
                def normalize(s: str) -> str:
                    if not s:
                        return ""
                    s = str(s)
                    s = re.sub(r'[。、！？\s]+', '', s)
                    return s

                sys_norm = normalize(self.current_system_text)
                user_norm = normalize(text)
                if sys_norm and user_norm and (user_norm in sys_norm or sys_norm in user_norm):
                    # 誤検出防止: 短すぎるものは弾く
                    if len(user_norm) > 2:
                        self.logger.info(f"[ASR_FILTER] Ignored system echo: {text!r} (matched system text)")
                        return None
        except Exception:
            # フィルタ処理で例外が発生しても通常処理は継続
            pass

        # 空文字チェックは簡素化
        if not text or len(text.strip()) == 0:
            self.logger.debug(f"[ASR_TRANSCRIPT] Empty text, skipping: call_id={call_id}")
            return None
       
        
        # call_id を self.call_id に保存（_append_call_log で使用）
        self.call_id = call_id
        
        # 【セッションログ保存】on_transcriptイベントをtranscript.jsonlに保存（JSONL形式で逐次追記）
        self._save_transcript_event(call_id, text, is_final, kwargs)
        
        # セッション情報を初期化（初回のみ）
        if call_id not in self.session_info:
            self.session_info[call_id] = {
                "start_time": datetime.now(),
                "intents": [],
                "phrases": [],
            }
        
        # ============================================================
        # partial（is_final=False）の場合は partial_transcripts に追記するだけ
        # ============================================================
        # 古いpartial transcriptsをクリーンアップ（定期的に実行）
        self._cleanup_stale_partials(max_age_sec=30.0)
        
        if not is_final:
            # partial_transcripts を初期化（存在しない場合）
            if call_id not in self.partial_transcripts:
                self.partial_transcripts[call_id] = {"text": "", "updated": time.time()}
            
            # partial テキストを更新
            if text:
                # Google ASR の partial は通常、前の partial を含む形で返ってくるため、
                # 単純に最新のtextで置き換えるだけで良い（連結不要）
                # 例: "もし" → "もしもし" → "もしもしホーム"
                # ただし、非累積的なケースも検出してログに記録
                prev_text = self.partial_transcripts[call_id].get("text", "")
                # テキスト比較時は正規化（先頭/末尾スペースを無視）
                prev_text_normalized = prev_text.strip() if prev_text else ""
                text_normalized = text.strip() if text else ""
                
                if prev_text and not text.startswith(prev_text) and prev_text not in text:
                    self.logger.warning(
                        f"[ASR_PARTIAL_NON_CUMULATIVE] call_id={call_id} "
                        f"prev={prev_text!r} new={text!r} (new does not start with prev)"
                    )
                # テキストが変わった場合はprocessedフラグをリセット（新しいテキストを処理可能にする）
                # 【修正3】正規化したテキストで比較（先頭/末尾スペース、句読点・記号の違いを無視）
                prev_text_normalized_clean = normalize_text_for_comparison(prev_text_normalized)
                text_normalized_clean = normalize_text_for_comparison(text_normalized)
                
                if prev_text_normalized_clean != text_normalized_clean:
                    self.partial_transcripts[call_id].pop("processed", None)
                # 正規化したテキストも保存（final処理時の比較用）
                self.partial_transcripts[call_id]["text_normalized"] = text_normalized
                self.partial_transcripts[call_id]["text"] = text
                self.partial_transcripts[call_id]["updated"] = time.time()
            
            # デバッグログ（DEBUGレベルに変更）
            merged_text = self.partial_transcripts[call_id]["text"]
            self.logger.debug(
                "[ASR_PARTIAL] call_id=%s partial=%r",
                call_id,
                merged_text,
            )
            
            # ChatGPT音声風: 短い部分認識をトリガーに即応答（バックチャネル）
            text_stripped = text.strip() if text else ""
            if 1 <= len(text_stripped) <= 6:
                backchannel_keywords = ["はい", "えっと", "あの", "ええ", "そう", "うん", "ああ"]
                if any(keyword in text_stripped for keyword in backchannel_keywords):
                    self.logger.debug(f"[BACKCHANNEL_TRIGGER] Detected short utterance: {text_stripped}")
                    # tts_callback が設定されている場合のみ実行
                    if hasattr(self, 'tts_callback') and self.tts_callback:  # type: ignore[attr-defined]
                        try:
                            try:
                                self.current_system_text = "はい"
                            except Exception:
                                pass
                            self.tts_callback(call_id, "はい", None, False)  # type: ignore[misc, attr-defined]
                            self.logger.info(f"[BACKCHANNEL_SENT] call_id={call_id} text='はい' (triggered by partial: {text_stripped!r})")
                        except Exception as e:
                            self.logger.exception(f"[BACKCHANNEL_ERROR] call_id={call_id} error={e}")
            
            # 【修正4】ASRレスポンスの高速化: GREETING（もしもし等）の早期検出
            merged_text = self.partial_transcripts[call_id].get("text", "")
            text_stripped = merged_text.strip() if merged_text else ""
            
            # GREETINGキーワードの早期検出（3文字以上で検出可能）
            greeting_keywords = ["もしもし", "もし", "おはよう", "こんにちは", "こんばんは", "失礼します"]
            is_greeting_detected = any(keyword in text_stripped for keyword in greeting_keywords)
            
            # GREETING検出時は3文字以上で即座に処理開始（低遅延モード）
            min_length_for_processing = 3 if is_greeting_detected else 5
            
            if merged_text and len(text_stripped) >= min_length_for_processing:
                # processedフラグをチェック（既に処理済みなら早期return）
                if self.partial_transcripts[call_id].get("processed"):
                    self.logger.debug(f"[ASR_SKIP_PARTIAL] Already processed: call_id={call_id} text={merged_text!r}")
                    return None
                
                # 未処理の場合のみ処理してフラグを保存（final時に重複処理しない）
                self.partial_transcripts[call_id]["processed"] = True
                # デバッグ: processedフラグ設定後の状態を確認
                self.logger.info(
                    f"[ASR_DEBUG_PARTIAL] call_id={call_id} "
                    f"partial_data_after_processed={self.partial_transcripts[call_id]}"
                )
                # GREETING検出時は低遅延モードで即座に処理開始
                if is_greeting_detected:
                    self.logger.info(
                        f"[ASR_PARTIAL_PROCESS] call_id={call_id} partial_text={merged_text!r} "
                        f"(GREETING detected, >=3 chars, low-latency mode)"
                    )
                else:
                    self.logger.info(
                        f"[ASR_PARTIAL_PROCESS] call_id={call_id} partial_text={merged_text!r} "
                        f"(>=5 chars, processing immediately)"
                    )
                # partialで処理した場合も、下の会話ロジックを実行する
                # processedフラグを立てているため、is_final=Trueで再度処理された場合は
                # 行3753-3764の重複チェックでスキップされる
                # （下の処理に進む）
            else:
                # partial の場合は会話ロジックを実行しない
                return None
        
        # ============================================================
        # ここから下は final（is_final=True）のときだけ実行される
        # ============================================================
        
        # partial_textを初期化（is_final=Falseの場合も使用される可能性があるため）
        partial_text = ""
        
        # final処理時にpartial処理済みなら早期return（重複再生防止）
        if is_final:
            # 【修正3】テキスト正規化: 句読点・記号を除去して比較
            # テキストを正規化して比較
            text_normalized = normalize_text_for_comparison(text)
            
            # partial_transcriptsに保存されている正規化テキストと比較
            # デバッグ: partial_transcriptsの内容を確認
            if call_id in self.partial_transcripts:
                self.logger.info(
                    f"[ASR_DEBUG_FINAL] call_id={call_id} "
                    f"partial_data={self.partial_transcripts[call_id]} "
                    f"text_normalized={text_normalized}"
                )
            else:
                self.logger.info(
                    f"[ASR_DEBUG_FINAL] call_id={call_id} "
                    f"partial_transcripts EMPTY, text_normalized={text_normalized}"
                )
            
            if call_id in self.partial_transcripts:
                partial_text_normalized = self.partial_transcripts[call_id].get("text_normalized", "")
                # 保存されているtext_normalizedも再正規化（句読点除去）
                if partial_text_normalized:
                    partial_text_normalized = normalize_text_for_comparison(partial_text_normalized)
                    # 正規化したテキストが同じで、かつprocessedフラグが立っている場合はスキップ
                    if partial_text_normalized == text_normalized and self.partial_transcripts[call_id].get("processed"):
                        self.logger.info(f"[ASR_SKIP_FINAL] Already processed as partial: call_id={call_id} text={text_normalized!r} (normalized)")
                        del self.partial_transcripts[call_id]
                        return None
                elif self.partial_transcripts[call_id].get("processed"):
                    # text_normalizedが保存されていない場合でも、processedフラグがあればスキップ
                    merged_text = self.partial_transcripts[call_id].get("text", "")
                    merged_text_normalized = normalize_text_for_comparison(merged_text)
                    if merged_text_normalized == text_normalized:
                        self.logger.info(f"[ASR_SKIP_FINAL] Already processed as partial: call_id={call_id} text={text_normalized!r} (normalized)")
                        del self.partial_transcripts[call_id]
                        return None
            
            # is_final=Trueで重複チェックを通過した場合のみ、partial_transcriptsを取り出してクリア
            if call_id in self.partial_transcripts:
                partial_text = self.partial_transcripts[call_id].get("text", "")
                self.logger.debug(f"[ASR_FINAL_MERGE] Merging partial='{partial_text}' with final='{text}'")
                # partial_transcripts をクリア
                del self.partial_transcripts[call_id]
        
        # 【最終活動時刻を更新】
        self.last_activity[call_id] = time.time()
        
        # 【再生中割り込み処理】再生中にASR入力があった場合はuuid_breakを実行（即時フラッシュ）
        # 応答速度最適化: 割り込み処理を非同期化し、軽い呼吸時間を確保してから次の処理に進む
        if self.is_playing.get(call_id, False):
            self.logger.info(f"[PLAYBACK_INTERRUPT] call_id={call_id} text={text!r} -> executing uuid_break (async)")
            self._break_playback(call_id)  # 非同期実行（ブロックしない）
            # 割り込み後はis_playingをFalseに設定（即座に次の再生を可能にする）
            self.is_playing[call_id] = False
            # runtime.logへの主要イベント出力
            runtime_logger = logging.getLogger("runtime")
            runtime_logger.info(f"UUID_BREAK call_id={call_id} text={text[:50]}")
            # 応答速度最適化: 軽い呼吸時間を確保（0.05秒）してから次の処理に進む
            # これにより「割り込んだ瞬間に返す」自然な会話感を実現
            time.sleep(0.05)  # 50msの軽い待機（割り込み処理の完了を待つ）
        
        # （partial_transcriptsの処理はis_finalブロック内に移動）
        
        # Google ASR の final は通常、全ての partial を含むため、
        # final が空でない限り final を使用
        merged_text = text if text else partial_text
        
        self.logger.info(
            f"[ASR_FINAL] call_id={call_id} "
            f"partial={partial_text!r} final={text!r} merged={merged_text!r}"
        )
        
        # 最小長チェック（2文字以上で処理）
        # ただし、1文字の曖昧な発話（「あ」「ん」「え」「お」）は NOT_HEARD として処理
        if len(merged_text) < MIN_TEXT_LENGTH_FOR_INTENT:
            if len(merged_text) == 1:
                ambiguous_chars = ["あ", "ん", "え", "お", "う", "い"]
                if merged_text in ambiguous_chars:
                    self.logger.debug(
                        f"[ASR_AMBIGUOUS] call_id={call_id} text={merged_text!r} -> treating as NOT_HEARD"
                    )
                    # NOT_HEARD として処理（110を返す）
                    intent = "NOT_HEARD"
                    template_ids = ["110"]
                    reply_text = self._render_templates(template_ids)
                    # TTS コールバック
                    if hasattr(self, 'tts_callback') and self.tts_callback:  # type: ignore[attr-defined]
                        try:
                            try:
                                self.current_system_text = reply_text or self._render_templates(template_ids) or ""
                            except Exception:
                                self.current_system_text = reply_text or ""
                            self.tts_callback(call_id, reply_text, template_ids, False)  # type: ignore[misc, attr-defined]
                            self.logger.info(
                                f"TTS_SENT: call_id={call_id} templates={template_ids} (NOT_HEARD for ambiguous 1-char)"
                            )
                        except Exception as e:
                            self.logger.exception(f"TTS_ERROR: call_id={call_id} error={e}")
                    return reply_text
            # それ以外の短い発話はスキップ
            self.logger.debug(
                f"[ASR_SHORT] call_id={call_id} text={merged_text!r} "
                f"len={len(merged_text)} -> skipping (too short)"
            )
            return None
        
        # ユーザー発話（確定）をログに記録（merged_text を使用）
        if merged_text:
            try:
                self._append_call_log("USER", merged_text)
            except Exception as e:
                # ログ記録の失敗は通話処理を止めない
                self.logger.exception("CALL_LOGGING_ERROR (USER): %s", e)
            
            # ユーザー発話時にno_input_streakをリセット
            state = self._get_session_state(call_id)
            if state.no_input_streak > 0:
                self.logger.info(
                    f"[NO_INPUT] call_id={call_id} streak reset (user input: {merged_text[:20]!r}...)"
                )
                state.no_input_streak = 0
        
        if not merged_text:
            return None
        
        # 幻聴フィルター（merged_text を使用）
        if self._is_hallucination(merged_text):
            self.logger.debug(">> Ignored hallucination (noise)")
            return None
        
        # 【追加】intent 判定直前のログ（DEBUGレベルに変更）
        self.logger.debug(
            "[ASR_DEBUG] merged_for_intent call_id=%s text=%r",
            call_id,
            merged_text,
        )
        
        # 会話フロー処理（intent判定、テンプレート選択など）（merged_text を使用）
        state = self._get_session_state(call_id)
        phase_before = state.phase
        
        # Intent判定（デバッグログ拡張: INTENT）
        intent = None
        normalized = ""
        if merged_text:
            # Intent方式は廃止されました。dialogue_flow方式を使用
            normalized = normalize_text(merged_text)
            intent = "UNKNOWN"  # Intent方式は廃止されました
            self.logger.info(f"[INTENT] {intent} (deprecated)")
            # runtime.logへの主要イベント出力
            runtime_logger = logging.getLogger("runtime")
            runtime_logger.info(f"INTENT call_id={call_id} intent={intent} text={merged_text[:50]}")
            
            # 【簡易Intent判定】ASR起動直後の簡易応答（はい/いいえ/その他）
            # Intent方式は廃止されました。dialogue_flow方式を使用
            simple_intent = self._classify_simple_intent(merged_text, normalized)
            if simple_intent:
                self.logger.info(f"[SIMPLE_INTENT] {simple_intent} (text={merged_text!r})")
                # 簡易Intentに応じて音声ファイルを再生
                self._play_audio_response(call_id, simple_intent)
                # 簡易応答の場合は、通常の会話フロー処理をスキップ（音声再生のみ）
                return None
        
        # 【FlowEngine統合】JSON定義ベースのフェーズ遷移処理
        # call_idに対応するFlowEngineを取得（クライアント別フロー対応）
        flow_engine = self.flow_engines.get(call_id) or self.flow_engine
        
        if flow_engine:
            try:
                # 【追加】フローエンジンへ渡す直前ログ
                try:
                    preview_for_flow = merged_text if isinstance(merged_text, str) else repr(merged_text)
                except Exception:
                    preview_for_flow = "<unrepresentable>"
                self.logger.info(f"[TRANSCRIPT_DEBUG] Passing text to FlowEngine for call_id={call_id} text={preview_for_flow!r}")
                # クライアントIDを取得（テンプレート再生時に使用）
                client_id = self.call_client_map.get(call_id) or state.meta.get("client_id") or self.client_id or "000"
                
                reply_text, template_ids, intent, transfer_requested = self._handle_flow_engine_transition(
                    call_id, merged_text, normalized, intent, state, flow_engine, client_id
                )
                phase_after = state.phase
                
                self.logger.info(
                    f"FLOW_ENGINE: call_id={call_id} client_id={client_id} "
                    f"phase={phase_before}->{phase_after} intent={intent} "
                    f"templates={template_ids} transfer={transfer_requested}"
                )
                # runtime.logへの主要イベント出力（詳細フォーマット）
                runtime_logger = logging.getLogger("runtime")
                template_str = ",".join(template_ids) if template_ids else "none"
                runtime_logger.info(f"[FLOW] call_id={call_id} phase={phase_before}→{phase_after} intent={intent} template={template_str}")
                
                # テンプレート再生処理（即時発火、待機なし）
                if template_ids:
                    # 応答速度最適化: 再生完了を待たずに即座に再生を開始
                    self._play_template_sequence(call_id, template_ids, client_id)
                
                # 転送処理
                if transfer_requested:
                    self._trigger_transfer_if_needed(call_id, state)
                
                return reply_text
            except Exception as e:
                self.logger.exception(f"[FLOW_ENGINE] Error in flow engine transition: {e}")
                # エラー時はフォールバックテンプレート（110: 聞き取れませんでした）を再生
                self.logger.warning(f"[FLOW_ENGINE] Using fallback template due to error: call_id={call_id}")
                try:
                    fallback_template_ids = ["110"]
                    client_id = self.call_client_map.get(call_id) or state.meta.get("client_id") or self.client_id or "000"
                    self._play_template_sequence(call_id, fallback_template_ids, client_id)
                except Exception as fallback_err:
                    self.logger.exception(f"[FLOW_ENGINE] Failed to play fallback template: {fallback_err}")
        
        # 空のテキスト（無音検出時）の場合は、no_input_streakに基づいてテンプレートを選択
        if not merged_text or len(merged_text.strip()) == 0:
            # 無音検出時の処理
            no_input_streak = state.no_input_streak
            self.logger.info(
                f"[NO_INPUT] call_id={call_id} streak={no_input_streak} (empty text detected)"
            )
            
            if no_input_streak == 1:
                template_ids = ["110"]
            elif no_input_streak == 2:
                template_ids = ["111"]
            else:
                template_ids = ["112"]
                # テンプレート112の場合は自動切断を予約
                if self.hangup_callback:
                    self.logger.info(
                        f"[NO_INPUT] call_id={call_id} template=112, scheduling auto_hangup delay=2.0s"
                    )
                    try:
                        self._schedule_auto_hangup(call_id, delay_sec=2.0)
                    except Exception as e:
                        self.logger.exception(
                            f"[NO_INPUT] AUTO_HANGUP_SCHEDULE_ERROR: call_id={call_id} error={e!r}"
                        )
            
            reply_text = self._render_templates(template_ids)
            intent = "NOT_HEARD"
            transfer_requested = False
            
            # last_ai_templatesを設定（TTS送信用）
            state.last_ai_templates = template_ids
            
            # ログ出力（発信者番号を含む）
            caller_number = getattr(self, "caller_number", None) or "未設定"
            self.logger.info(
                f"[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} template={template_ids[0] if template_ids else 'NONE'}"
            )
        else:
            # 通常の処理（ユーザー発話あり）
            reply_text, template_ids, intent, transfer_requested = self._generate_reply(call_id, merged_text)
            # Intentログは既に上で出力済み（merged_textがある場合）
        
        # 状態取得（一度だけ）
        phase_after = state.phase
        
        self.logger.info(
            f"CONV_FLOW: call_id={call_id} "
            f"phase={phase_before}->{phase_after} intent={intent} "
            f"templates={template_ids} transfer={transfer_requested}"
        )

        # END 遷移時の自動切断（転送しない場合のみ）
        if phase_before != "END" and phase_after == "END" and not state.transfer_requested:
            self.logger.info(
                f"AUTO_HANGUP: scheduling for call_id={call_id}"
            )
            self._schedule_auto_hangup(call_id, delay_sec=60.0)

        # AI応答をログ記録
        self._log_ai_templates(template_ids)

        if not reply_text:
            self.logger.debug("No reply generated for call_id=%s (phase=%s)", call_id, phase_after)
            # 転送要求があるが返答テキストがない場合でも転送処理を実行
            if transfer_requested:
                self._trigger_transfer_if_needed(call_id, state)
            return None
        
        # 【改善1】INTROフェーズ中はENTRYテンプレート送信を抑制（intro再生中の被り防止）
        # 注意: ログ、state更新、会話フロー処理は通常通り実行し、TTS送信だけを抑制
        # 【修正1】state.phase を直接参照（phase_after はフロー処理後に更新されている可能性があるため）
        current_phase = state.phase
        if current_phase == "INTRO":
            self.logger.debug(
                f"[AICORE] Phase=INTRO, skipping TTS (intro playing) call_id={call_id} "
                f"templates={template_ids} (other processing completed)"
            )
            # TTS送信は抑制するが、転送処理は実行（転送要求がある場合）
            # 【修正3】_trigger_transfer_if_needed() は転送処理のみ（TTS送信はしない）前提
            if transfer_requested:
                self._trigger_transfer_if_needed(call_id, state)
            # 【修正2】返り値はログ用のみ（呼び出し側で別チャネル送信はしない前提）
            return reply_text  # ログ記録などのために返答テキストは返す
        
        # TTS コールバック（転送要求フラグも渡す）
        # 注意: transfer_requested=True の場合、_send_tts 内でTTS送信完了後に転送処理が開始される
        if hasattr(self, 'tts_callback') and self.tts_callback:  # type: ignore[attr-defined]
            try:
                try:
                    self.current_system_text = reply_text or self._render_templates(template_ids) or ""
                except Exception:
                    self.current_system_text = reply_text or ""
                self.tts_callback(call_id, reply_text, template_ids, transfer_requested)  # type: ignore[misc, attr-defined]
                self.logger.info(
                    f"TTS_SENT: call_id={call_id} templates={template_ids} transfer_requested={transfer_requested}"
                )
            except Exception as e:
                self.logger.exception(f"TTS_ERROR: call_id={call_id} error={e}")
        
        # 転送処理は _send_tts 内でTTS送信完了後に実行されるため、ここでは実行しない
        # （transfer_requested=True の場合、_send_tts 内で _wait_for_tts_and_transfer が起動される）
        
        return reply_text
    
    def _log_ai_templates(self, template_ids: List[str]) -> None:
        """AI応答のログ記録を分離"""
        try:
            from .text_utils import TEMPLATE_CONFIG
            for tid in template_ids:
                cfg = TEMPLATE_CONFIG.get(tid)
                if cfg and cfg.get("text"):
                    self._append_call_log("AI", cfg["text"], template_id=tid)
        except Exception as e:
            self.logger.exception(f"CALL_LOGGING_ERROR (AI): {e}")
    
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

    def _schedule_auto_hangup(self, call_id: str, delay_sec: float = 2.0) -> None:
        """
        自動切断をスケジュールする（無音タイムアウト時など）
        
        :param call_id: 通話ID
        :param delay_sec: 切断までの遅延時間（秒）
        """
        if not self.hangup_callback:
            self.logger.warning(
                f"[AUTO_HANGUP] call_id={call_id} hangup_callback not set, cannot schedule hangup"
            )
            return
        
        key = call_id or "GLOBAL_CALL"
        
        # 既存のタイマーがあればキャンセル
        if key in self._auto_hangup_timers:
            old_timer = self._auto_hangup_timers.pop(key)
            try:
                old_timer.cancel()
                self.logger.debug(f"[AUTO_HANGUP] canceled existing timer for call_id={call_id}")
            except Exception as e:
                self.logger.warning(f"[AUTO_HANGUP] failed to cancel old timer: {e}")
        
        # 新しいタイマーをスケジュール
        def do_hangup():
            try:
                self.logger.info(
                    f"[AUTO_HANGUP] executing hangup for call_id={call_id} after {delay_sec}s delay"
                )
                if self.hangup_callback:
                    self.hangup_callback(call_id)
                    self.logger.info(f"[AUTO_HANGUP] hangup_callback executed for call_id={call_id}")
                else:
                    self.logger.error(f"[AUTO_HANGUP] hangup_callback was None when timer fired for call_id={call_id}")
            except Exception as e:
                self.logger.exception(f"[AUTO_HANGUP] error executing hangup for call_id={call_id}: {e}")
            finally:
                # タイマーを辞書から削除
                self._auto_hangup_timers.pop(key, None)
        
        timer = threading.Timer(delay_sec, do_hangup)
        timer.daemon = True
        timer.start()
        self._auto_hangup_timers[key] = timer
        
        self.logger.info(
            f"[AUTO_HANGUP] scheduled hangup for call_id={call_id} delay={delay_sec}s"
        )
    
    def reset_call(self, call_id: str) -> None:
        """
        ストリーミングモード: call_idの状態をリセット（通話終了時など）。
        
        :param call_id: 通話ID
        """
        # 通話開始フラグをクリア（on_new_audioでのスキップに必要）
        self._call_started_calls.discard(call_id)
        self.logger.info(f"[CLEANUP] Removed call_id={call_id} from _call_started_calls")
        
        if self.streaming_enabled and self.asr_model is not None:
            # GoogleASR の場合は end_stream を呼び出す
            if self.asr_provider == "google":
                try:
                    self.logger.info(f"[CLEANUP] Calling end_stream for call_id={call_id}")
                    self.asr_model.end_stream(call_id)  # type: ignore[union-attr]
                    self.logger.info(f"[CLEANUP] end_stream completed for call_id={call_id}")
                except Exception as e:
                    self.logger.error(f"[CLEANUP] GoogleASR end_stream failed for call_id={call_id}: {e}", exc_info=True)
            self.asr_model.reset_call(call_id)  # type: ignore[union-attr]
        self._reset_session_state(call_id)
        # 【追加】partial_transcripts もクリア
        if call_id in self.partial_transcripts:
            del self.partial_transcripts[call_id]
        # AUTO HANGUP TIMER もクリア
        # 注意: _schedule_auto_hangup でも既存タイマーをキャンセルしているが、
        # reset_call では通話終了時のクリーンアップとして実行する
        key = call_id or "GLOBAL_CALL"
        timer = self._auto_hangup_timers.pop(key, None)
        if timer is not None:
            try:
                timer.cancel()
                self.logger.info(
                    "AUTO_HANGUP_TIMER_CANCELED: call_id=%s", key
                )
            except Exception as e:
                self.logger.warning(
                    "AUTO_HANGUP_TIMER_CANCEL_ERROR: call_id=%s error=%r",
                    key, e
                )