"""ASR handlers shared between AICore and realtime gateway."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from libertycall.client_loader import load_client_profile
from .google_asr import GoogleASR
from .asr_audio_processor import ASRAudioProcessor
from .asr_stream_handler import ASRStreamHandler
from .asr_rtp_buffer import ASRRTPBuffer
from .asr_batch_handler import ASRBatchHandler

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


# ★ 転送先電話番号 (デフォルト)
OPERATOR_NUMBER = "08024152649"


@dataclass
class DialogueResult:
    call_id: str
    user_audio: bytes
    text_raw: Optional[str]
    intent: Optional[str]
    reply_text: Optional[str]
    tts_audio_24k: Optional[bytes]
    should_transfer: bool
    rms_avg: float
    duration_sec: float


@dataclass
class ASRProcessResult:
    dialogue: Optional[DialogueResult] = None
    barge_in_triggered: bool = False
    reset_no_input_timer: bool = False


@dataclass
class CallAudioState:
    audio_buffer: bytearray = field(default_factory=bytearray)
    turn_rms_values: List[int] = field(default_factory=list)
    is_user_speaking: bool = False
    current_segment_start: Optional[float] = None
    last_voice_wall: float = field(default_factory=time.time)
    last_voice_mono: float = field(default_factory=time.monotonic)
    last_silence_mono: Optional[float] = None
    backchannel_sent: bool = False
    stream_chunk_counter: int = 0
    last_feed_time: float = field(default_factory=time.time)


def init_asr(core) -> None:
    asr_provider = os.getenv("LC_ASR_PROVIDER", "google").lower()
    if asr_provider not in ["google", "whisper"]:
        raise ValueError(
            f"未知のASRプロバイダ: {asr_provider}\n"
            "有効な値: 'google' または 'whisper'\n"
            "（'local' はサポートされていません。'whisper' を使用してください。）"
        )

    core.asr_provider = asr_provider
    core.logger.info("AICore: ASR provider = %s", asr_provider)

    core.streaming_enabled = os.getenv("LC_ASR_STREAMING_ENABLED", "0") == "1"

    if core.init_clients:
        if asr_provider == "google":
            phrase_hints = core._load_phrase_hints()
            try:
                core.asr_model = GoogleASR(
                    language_code="ja",
                    sample_rate=16000,
                    phrase_hints=phrase_hints,
                    ai_core=core,
                    error_callback=core._on_asr_error,
                )
                core.logger.info("AICore: GoogleASR を初期化しました")
                core._phrase_hints = phrase_hints
            except Exception as exc:
                error_msg = str(exc)
                if "was not found" in error_msg or "credentials" in error_msg.lower():
                    core.logger.error(
                        "AICore: GoogleASR の初期化に失敗しました（認証エラー）: %s\n"
                        "環境変数 LC_GOOGLE_PROJECT_ID と LC_GOOGLE_CREDENTIALS_PATH を確認してください。\n"
                        "ASR機能は無効化されますが、GatewayはRTP受信を継続します。",
                        error_msg,
                    )
                else:
                    core.logger.error(
                        "AICore: GoogleASR の初期化に失敗しました: %s\n"
                        "ASR機能は無効化されますが、GatewayはRTP受信を継続します。",
                        error_msg,
                    )
                core.asr_model = None
                core.logger.warning("AICore: ASR機能なしでGatewayを起動します（RTP受信は継続されます）")
        elif asr_provider == "whisper":
            from libertycall.asr.whisper_local import WhisperLocalASR  # type: ignore[import-untyped]

            core.logger.debug("AICore: Loading Whisper via WhisperLocalASR...")
            core.asr_model = WhisperLocalASR(
                model_name="base",
                input_sample_rate=16000,
                language="ja",
                device="cpu",
                compute_type="int8",
                temperature=0.0,
                vad_filter=False,
                vad_parameters=None,
            )
            core.logger.info("AICore: WhisperLocalASR を初期化しました")

        if core.streaming_enabled:
            core.logger.info("AICore: ストリーミングASRモード有効")

        core._init_tts()
        core.logger.info(
            "ASR_BOOT: provider=%s streaming_enabled=%s",
            asr_provider,
            core.streaming_enabled,
        )
    else:
        core.logger.info(
            "AICore: init_clients=False のため ASR/TTS 初期化をスキップします (simulation mode)"
        )


def on_new_audio(core, call_id: str, pcm16k_bytes: bytes) -> None:
    ASRStreamHandler.handle_new_audio(core, call_id, pcm16k_bytes)


class GatewayASRManager:
    """Move RTP/ASR processing logic out of RealtimeGateway."""

    def __init__(self, gateway: "RealtimeGateway") -> None:
        super().__setattr__("gateway", gateway)
        super().__setattr__("logger", gateway.logger)
        super().__setattr__("audio_processor", ASRAudioProcessor(self))
        super().__setattr__("stream_handler", ASRStreamHandler(self))
        super().__setattr__("rtp_buffer", ASRRTPBuffer(self))
        super().__setattr__("batch_handler", ASRBatchHandler(self))
        super().__setattr__("operator_number", OPERATOR_NUMBER)

    def __getattr__(self, name: str):
        return getattr(self.gateway, name)

    def __setattr__(self, name: str, value) -> None:
        if name in {"gateway", "logger"}:
            super().__setattr__(name, value)
        else:
            setattr(self.gateway, name, value)

    async def process_rtp_audio(self, data: bytes, addr: Tuple[str, int]):
        # 【修正】条件分岐の「外」でログを出す
        current_time = time.time()
        self.logger.warning(f"[RTP_ENTRY] Time={current_time:.3f} Len={len(data)} Addr={addr}")

        # 先頭12バイト(RTPヘッダ)を解析
        sequence_number = None
        try:
            if len(data) >= 12:
                v_p_x_cc = data[0]
                m_pt = data[1]
                sequence_number = (data[2] << 8) | data[3]
                timestamp = (data[4] << 24) | (data[5] << 16) | (data[6] << 8) | data[7]
                ssrc = (data[8] << 24) | (data[9] << 16) | (data[10] << 8) | data[11]
                payload_type = m_pt & 0x7F
                marker = (m_pt >> 7) & 1

                self.logger.warning(
                    f"[RTP_RAW] Time={current_time:.3f} Len={len(data)} PT={payload_type} "
                    f"SSRC={ssrc:08x} Seq={sequence_number} Mark={marker} Addr={addr}"
                )
                self.logger.info(
                    f"[RTP_RAW] Time={current_time:.3f} Len={len(data)} PT={payload_type} "
                    f"SSRC={ssrc:08x} Seq={sequence_number} Mark={marker} Addr={addr}"
                )
        except Exception as e:
            self.logger.warning(f"[RTP_RAW_ERR] Failed to parse header: {e}")

        # RTPパケット受信ログ（必ず出力）
        self.logger.debug(f"[RTP_RECV] packet received from {addr}, len={len(data)}")
        try:
            # RTPパケット受信カウンターを初期化（存在しない場合）
            if not hasattr(self, "_rtp_recv_count"):
                self._rtp_recv_count = 0
            self._rtp_recv_count += 1

            # FreeSWITCH 双方向化: 受信元のアドレス/ポートへ返信する
            incoming_peer = (addr[0], addr[1])
            last_peer_state = self.rtp_peer  # RTP確立前の状態を記録
            if self.rtp_peer is None:
                self.logger.warning(
                    f"[RTP_INIT] First RTP packet from {addr}, setting peer to {incoming_peer}"
                )
                self.rtp_peer = incoming_peer
                queue_len = len(self.tts_queue)
                self.logger.info(
                    f"[RTP_RECONNECTED] rtp_peer={self.rtp_peer}, received from {addr}, queue_len={queue_len}"
                )
                if queue_len > 0:
                    self.logger.info(
                        f"[TTS_SENDER] RTP peer established: {self.rtp_peer}, {queue_len} queued packets will be sent"
                    )
                else:
                    self.logger.info(
                        f"[TTS_SENDER] RTP peer established: {self.rtp_peer}, queue_len={queue_len}"
                    )
            elif self.rtp_peer != incoming_peer:
                # 送信元が変わった場合は最新の送信元へ更新
                self.logger.warning(
                    f"[RTP_PEER_FIXED] RTP peer was {self.rtp_peer}, updating to {incoming_peer}"
                )
                self.rtp_peer = incoming_peer
            elif self._rtp_recv_count % 100 == 0:
                self.logger.debug(
                    f"[RTP_RECV] received {self._rtp_recv_count} packets from {addr}"
                )
        except Exception as e:
            self.logger.error(f"[RTP_RECV_ERROR] {e}", exc_info=True)

        self.logger.debug(
            "HANDLE_RTP_ENTRY: len=%d addr=%s call_completed=%s call_id=%s",
            len(data),
            addr,
            getattr(self, "call_completed", False),
            getattr(self, "call_id", None),
        )
        now = time.time()
        # FreeSWITCH双方向化: rtp_peerは上記で既に設定済み（incoming_peer）
        # 上書きしない（FreeSWITCHは受信元アドレスに送信する必要がある）
        # 受信元アドレスの変更を検出（通話の切り替えなど）
        if not hasattr(self, "_rtp_src_addr"):
            self._rtp_src_addr = None
        if self._rtp_src_addr is None:
            self._rtp_src_addr = addr
            self.logger.debug(f"RTP source address set: {addr}")
        elif addr != self._rtp_src_addr:
            idle = now - self.last_rtp_packet_time if self.last_rtp_packet_time else None
            if idle is None or idle >= self.RTP_PEER_IDLE_TIMEOUT:
                self.logger.info(
                    "RTP source changed from %s to %s (idle=%.2fs) -> resetting call state",
                    self._rtp_src_addr,
                    addr,
                    idle if idle is not None else -1.0,
                )
                if self.call_id:
                    self._complete_console_call()
                # ★ 常に完全なリセットを実行
                self._reset_call_state()
                self._rtp_src_addr = addr
                self.logger.debug(f"RTP source re-bound: {addr}")
            else:
                self.logger.debug(
                    "Ignoring unexpected RTP packet from %s (active peer=%s idle=%.2fs)",
                    addr,
                    self.rtp_peer,
                    idle,
                )
                return

        self.last_rtp_packet_time = now

        if len(data) <= 12:
            return

        # RTPペイロードを抽出（μ-law）
        pcm_data = self.audio_processor.extract_rtp_payload(data)

        # 最初のRTP到着時に初期音声を強制再生
        effective_call_id = self._get_effective_call_id(addr)

        self.audio_processor.log_rtp_payload_debug(pcm_data, effective_call_id)
        if not effective_call_id:
            self.logger.warning(f"[RTP_WARN] Unknown RTP source {addr}, skipping frame")
            return  # TEMP_CALLを使わずスキップ

        # 通話が既に終了している場合は処理をスキップ（ゾンビ化防止）
        # 【修正】RTPパケットが届いているという事実は「通話が生きている」証拠なので、強制登録する
        # ★RTP_RECOVERY の回数制限（ゾンビ蘇生防止）★
        if hasattr(self, "_active_calls") and effective_call_id not in self._active_calls:
            count = self._recovery_counts.get(effective_call_id, 0)
            if count >= 1:
                # 2回目以降はリカバリしない（ゾンビ蘇生防止）
                if count == 1:  # ログ抑制のため1回だけ出す
                    self.logger.warning(
                        f"[RTP_SKIP] Call {effective_call_id} recovery limit reached (count={count+1}), skipping recovery."
                    )
                return

            current_time = time.time()
            self._recovery_counts[effective_call_id] = count + 1
            self.logger.warning(
                f"[RTP_RECOVERY] [LOC_01] Time={current_time:.3f} call_id={effective_call_id} not in active_calls but receiving RTP. Auto-registering (Attempt {count+1})."
            )
            self.logger.warning(
                "[RTP_RECOVERY] [LOC_01] This is a recovery call. Initial sequence may need to be queued if not already played."
            )
            self._active_calls.add(effective_call_id)
            # return はしない！そのまま処理を続行させる

        # RTPパケットの重複処理ガード（シーケンス番号チェック）
        if not self.rtp_buffer.should_process(sequence_number, effective_call_id, addr):
            return

        # ログ出力（RTP受信時のcall_id確認用）
        self.logger.debug(
            f"[HANDLE_RTP_ENTRY] len={len(data)} addr={addr} call_id={effective_call_id}"
        )

        # 無音判定（RTPペイロードのエネルギー判定）
        if effective_call_id:
            self.audio_processor.update_vad_state(effective_call_id, pcm_data)

        # call_idが未設定の場合は、最初のRTPパケット受信時に設定
        if not self.call_id:
            self._ensure_console_session()

        # 最初のRTPパケット受信時に _active_calls に登録（確実なタイミング）
        # effective_call_id は上記の無音判定ブロックで取得済み
        if effective_call_id and effective_call_id not in self._active_calls:
            self.logger.warning(
                f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls at {time.time():.3f}"
            )
            self._active_calls.add(effective_call_id)
            self.logger.debug(
                f"[RTP_ACTIVE] Registered call_id={effective_call_id} to _active_calls"
            )
            # アドレスとcall_idのマッピングを保存
            if addr:
                self._call_addr_map[addr] = effective_call_id
                self.logger.debug(f"[RTP_ADDR_MAP] Mapped {addr} -> {effective_call_id}")

        # フォールバック: _active_calls が空で、effective_call_id が取得できない場合でも強制登録
        # FreeSWITCH の rtp_stream 経由では session_id が渡らないため、この処理が必要
        if not self._active_calls:
            # effective_call_id が取得できなかった場合は、アドレスベースで仮の通話IDを生成
            if not effective_call_id:
                # アドレスから一意の通話IDを生成（例: "rtp_127.0.0.1_7002"）
                fallback_call_id = f"rtp_{addr[0]}_{addr[1]}"
                effective_call_id = fallback_call_id
                self.logger.info(
                    f"[RTP_ACTIVE] Force-register call_id={fallback_call_id} (no existing session detected, addr={addr})"
                )
            else:
                self.logger.info(
                    f"[RTP_ACTIVE] Force-register call_id={effective_call_id} (_active_calls was empty, addr={addr})"
                )

            # 強制登録
            self.logger.warning(
                f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls (fallback) at {time.time():.3f}"
            )
            self._active_calls.add(effective_call_id)
            # アドレスとcall_idのマッピングを保存
            if addr:
                self._call_addr_map[addr] = effective_call_id
                self.logger.debug(f"[RTP_ADDR_MAP] Mapped {addr} -> {effective_call_id}")

            # 無音監視用の初期値を設定
            if effective_call_id not in self._last_voice_time:
                self._last_voice_time[effective_call_id] = time.monotonic()
            if effective_call_id not in self._last_tts_end_time:
                self._last_tts_end_time[effective_call_id] = time.monotonic()

        # 最大通話時間チェック
        if self.call_start_time is not None:
            elapsed = time.time() - self.call_start_time
            if elapsed > self.max_call_duration_sec:
                self.logger.warning(
                    f"[CALL_TIMEOUT] 最大通話時間({self.max_call_duration_sec}秒)を超過。通話を終了します: call_id={self.call_id}, elapsed={elapsed:.1f}秒"
                )
                # 非同期処理なので、タスクとして実行
                asyncio.create_task(
                    self._handle_hangup(self.call_id, reason="max_duration_exceeded")
                )
                return

        # RTPパケット受信ログ（Google使用時は毎回INFO、それ以外は50パケットに1回）
        self.rtp_packet_count += 1
        asr_provider = getattr(self.ai_core, "asr_provider", "google")
        is_google_streaming = asr_provider == "google" and self.streaming_enabled

        # 最初の RTP パケット受信時に client_id を識別
        # FreeSWITCH 側で local_rtp_port を destination_number+100 としているため、送信元ポートから決定する
        # 例: 7002 -> local 7102 -> client_id 7002 / 7003 -> local 7103 -> client_id 7003
        if not self.client_id and self.rtp_packet_count == 1:
            src_port = addr[1]
            inferred_client_id = None
            try:
                if 7100 <= src_port <= 8100:
                    inferred = src_port - 100
                    if 7000 <= inferred <= 7999:
                        inferred_client_id = str(inferred)
            except Exception:
                inferred_client_id = None

            if not inferred_client_id:
                inferred_client_id = os.getenv("LC_CLIENT_ID_FROM_FS") or self.default_client_id
                self.logger.info(
                    f"[CLIENT_ID_DEFAULT] src_port={src_port} -> client_id={inferred_client_id}"
                )
            else:
                self.logger.info(
                    f"[CLIENT_ID_DETECTED] src_port={src_port} -> client_id={inferred_client_id}"
                )

            self.client_id = inferred_client_id

            # クライアントプロファイルをロード
            try:
                self.client_profile = load_client_profile(self.client_id)
                self.rules = self.client_profile.get("rules", {})
                self.logger.info(
                    f"[CLIENT_PROFILE_LOADED] client_id={self.client_id}"
                )
            except FileNotFoundError:
                self.logger.warning(
                    f"[CLIENT_PROFILE_NOT_FOUND] client_id={self.client_id}, using default"
                )
                self.client_profile = None
                self.rules = {}
            except Exception as e:
                self.logger.error(
                    f"[CLIENT_PROFILE_ERROR] Failed to load profile for {self.client_id}: {e}",
                    exc_info=True,
                )
                self.client_profile = None
                self.rules = {}

        # 最初の RTP パケット受信時に初回シーケンスを enqueue
        # client_id が設定されていない場合は default_client_id を使用
        if not self.initial_sequence_played and self.rtp_packet_count == 1:
            effective_client_id = self.client_id or self.default_client_id
            if effective_client_id:
                # 非同期タスクとして実行（結果を待たない）
                task = asyncio.create_task(
                    self._queue_initial_audio_sequence(effective_client_id)
                )

                def _log_init_task_result(t):
                    try:
                        t.result()  # 例外があればここで再送出される
                    except Exception as e:
                        import traceback

                        self.logger.error(
                            f"[INIT_TASK_ERR] Initial sequence task failed: {e}\n{traceback.format_exc()}"
                        )

                task.add_done_callback(_log_init_task_result)
                self.logger.warning(
                    f"[INIT_TASK_START] Created task for {effective_client_id}"
                )
            else:
                self.logger.warning(
                    "No client_id available for initial sequence, skipping"
                )

            # 録音開始（最初の RTP パケット受信時）
            if self.recording_enabled and self.recording_file is None:
                self._start_recording()

        if is_google_streaming:
            # Google使用時は毎回INFOレベルで出力（idx付き）
            self.logger.info(
                "RTP_RECV: n=%d time=%.3f from=%s size=%d",
                self.rtp_packet_count,
                time.time(),
                addr,
                len(data),
            )
        elif self.rtp_packet_count == 1:
            self.logger.info(f">> RTP packet received from {addr}, size={len(data)}")
        elif self.rtp_packet_count % 50 == 0:
            self.logger.info(
                f">> RTP packet received (count={self.rtp_packet_count}) from {addr}, size={len(data)}"
            )
        else:
            self.logger.debug(
                f">> RTP packet received from {addr}, size={len(data)}"
            )

        # pcm_data は既に上で抽出済み（無音判定で使用）

        try:
            pcm16k_chunk, rms = self.audio_processor.process_pcm_payload(
                pcm_data,
                effective_call_id,
            )

            # --- 初回シーケンス再生中は ASR には送らない（録音とRMSだけ） ---
            if self.initial_sequence_playing:
                # 録音は続けるが、ASRには一切送らない
                # デバッグログ追加
                self.logger.debug(
                    f"[ASR_DEBUG] initial_sequence_playing={self.initial_sequence_playing}, streaming_enabled={self.streaming_enabled}, skipping ASR feed"
                )
                return

            # --- Pull型ASR: 002.wav再生完了までASRをスキップ ---
            # TODO: テスト完了後、このチェックを有効化して本番構成に戻す
            # if not self.fs_rtp_monitor.asr_active:
            #     if not hasattr(self, '_asr_wait_logged'):
            #         self.logger.info(
            #             "[FS_RTP_MONITOR] ASR_WAIT: Waiting for 002.wav playback completion (asr_active=False)"
            #         )
            #         self._asr_wait_logged = True
            #     return
            # if hasattr(self, '_asr_wait_logged'):
            #     delattr(self, '_asr_wait_logged')

            # --- ストリーミングモード: チャンクごとにfeed ---
            # Google使用時は全チャンクを無条件で送信（VAD/バッファリングなし）
            if self.streaming_enabled:
                if self.stream_handler.handle_streaming_chunk(pcm16k_chunk, rms):
                    return

            self.batch_handler.handle_batch_chunk(pcm16k_chunk, rms)

        except Exception as e:
            self.logger.error(f"AI Error: {e}")

    async def handle_asr_result(
        self, text: str, audio_duration: float, inference_time: float, end_to_text_delay: float
    ):
        await self.stream_handler.handle_asr_result(
            text,
            audio_duration,
            inference_time,
            end_to_text_delay,
        )


