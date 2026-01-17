"""ASR handlers shared between AICore and realtime gateway."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import threading
import time
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from libertycall.client_loader import load_client_profile
from libertycall.console_bridge import console_bridge
from libertycall.gateway.audio_utils import pcm24k_to_ulaw8k
from libertycall.gateway.text_utils import normalize_text
from .google_asr import GoogleASR
from .asr_audio_processor import ASRAudioProcessor
from .asr_stream_handler import ASRStreamHandler
from .asr_rtp_buffer import ASRRTPBuffer

try:  # pragma: no cover - optional dependency
    from scapy.all import IP, UDP, sniff

    SCAPY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SCAPY_AVAILABLE = False

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

            # --- バッファリング（非ストリーミングモード） ---
            # 初回シーケンス再生中は ASR をブロック（000→001→002 が必ず流れるように）
            if self.initial_sequence_playing:
                self.logger.debug(
                    f"[ASR_DEBUG] initial_sequence_playing={self.initial_sequence_playing}, streaming_enabled={self.streaming_enabled}, skipping audio_buffer (Batch ASR mode)"
                )
                return

            self.audio_buffer.extend(pcm16k_chunk)
            self.logger.debug(
                f"[ASR_DEBUG] Added {len(pcm16k_chunk)} bytes to audio_buffer (total={len(self.audio_buffer)} bytes, streaming_enabled={self.streaming_enabled})"
            )

            # ★ 最初の音声パケット到達時刻を記録
            if self.current_segment_start is None:
                self.current_segment_start = time.time()

            # --- streaming_enabledに関係なくis_user_speakingを更新（Batch ASRモードでも動作するように） ---
            # BARGE_IN_THRESHOLDはTTS停止用の閾値、MIN_RMS_FOR_SPEECHはASR用の閾値として使用
            # ここでは、音声検出用のより低い閾値を使用（または常に更新）
            MIN_RMS_FOR_SPEECH = 80  # ASR用の最小RMS閾値（BARGE_IN_THRESHOLD=1000より低い）
            if rms > MIN_RMS_FOR_SPEECH:
                if not self.is_user_speaking:
                    self.is_user_speaking = True
                    self.last_voice_time = time.time()
                self.turn_rms_values.append(rms)
            elif rms <= MIN_RMS_FOR_SPEECH:
                # 無音が続く場合はis_user_speakingをFalseに（ただし、turn_rms_valuesには追加しない）
                # 既に蓄積されたRMS値は保持される
                pass

            # デバッグログ
            self.logger.info(
                f"[ASR_DEBUG] RMS={rms:.1f}, is_user_speaking={self.is_user_speaking}, turn_rms_count={len(self.turn_rms_values)}, streaming_enabled={self.streaming_enabled}"
            )

            # --- ストリーミングモードでは従来のバッファリング処理をスキップ ---
            if self.streaming_enabled:
                return

            # --- ターミネート(区切り)判定（非ストリーミングモード） ---
            now = time.time()
            time_since_voice = now - self.last_voice_time

            # セグメント経過時間を計算 (未開始なら0)
            segment_elapsed = 0.0
            if self.current_segment_start is not None:
                segment_elapsed = now - self.current_segment_start

            # ★ ハイブリッド条件
            # 1. 無音が SILENCE_DURATION 続いた
            # 2. または、話し始めてから MAX_SEGMENT_SEC 経過した
            should_cut = False

            # A. 無音タイムアウト
            if self.is_user_speaking and time_since_voice > self.SILENCE_DURATION:
                should_cut = True

            # B. 最大時間タイムアウト (音声がある場合のみ)
            elif len(self.audio_buffer) > 0 and segment_elapsed > self.MAX_SEGMENT_SEC:
                should_cut = True
                self.logger.debug(
                    f">> MAX SEGMENT REACHED ({segment_elapsed:.2f}s). Forcing cut."
                )

            if should_cut:
                # ノイズ除去: バッファが短すぎる場合は破棄
                if len(self.audio_buffer) < self.MIN_AUDIO_LEN:
                    self.logger.debug(
                        f"[ASR_DEBUG] Segment too short: {len(self.audio_buffer)} < {self.MIN_AUDIO_LEN}, skipping"
                    )
                    self.audio_buffer = bytearray()
                    self.turn_rms_values = []
                    self.current_segment_start = None  # リセット
                    return

                self.logger.info(
                    f"[ASR_DEBUG] >> Processing segment... (buffer_size={len(self.audio_buffer)}, time_since_voice={time_since_voice:.2f}s, segment_elapsed={segment_elapsed:.2f}s)"
                )
                # セグメント処理開始時のturn_rms_valuesの状態をログ出力
                self.logger.info(
                    f"[ASR_DEBUG] turn_rms_values: count={len(self.turn_rms_values)}, values={self.turn_rms_values[:10] if len(self.turn_rms_values) > 0 else 'empty'}"
                )
                self.is_user_speaking = False

                user_audio = bytes(self.audio_buffer)

                # RMSベースのノイズゲート: 低RMSのセグメントはASRに送らない
                # RMS平均計算の直前にもログ追加
                self.logger.info(
                    f"[ASR_DEBUG] Before RMS avg calculation: turn_rms_values count={len(self.turn_rms_values)}"
                )
                if self.turn_rms_values:
                    rms_avg = sum(self.turn_rms_values) / len(self.turn_rms_values)
                else:
                    rms_avg = 0

                self.logger.info(
                    f"[ASR_DEBUG] RMS check: rms_avg={rms_avg:.1f}, MIN_RMS_FOR_ASR={self.MIN_RMS_FOR_ASR}"
                )
                if rms_avg < self.MIN_RMS_FOR_ASR:
                    self.logger.info(
                        f"[ASR_DEBUG] >> Segment skipped due to low RMS (rms_avg={rms_avg:.1f} < {self.MIN_RMS_FOR_ASR})"
                    )
                    # セグメントを破棄してリセット
                    self.audio_buffer.clear()
                    self.turn_rms_values = []
                    self.current_segment_start = None
                    self.is_user_speaking = False
                    return

                # 処理開始前にバッファとタイマーをリセット
                self.audio_buffer = bytearray()
                self.current_segment_start = None

                # AI処理実行
                self.logger.info(
                    f"[ASR_DEBUG] Calling process_dialogue with {len(user_audio)} bytes (streaming_enabled={self.streaming_enabled}, initial_sequence_playing={self.initial_sequence_playing})"
                )
                self._ensure_console_session()
                (
                    tts_audio_24k,
                    should_transfer,
                    text_raw,
                    intent,
                    reply_text,
                ) = self.ai_core.process_dialogue(user_audio)
                self.logger.info(
                    f"[ASR_DEBUG] process_dialogue returned: text_raw={text_raw}, intent={intent}, should_transfer={should_transfer}"
                )

                # 音声が検出された際に無音検知タイマーをリセット
                if text_raw and intent != "IGNORE":
                    effective_call_id = self._get_effective_call_id()
                    if effective_call_id:
                        self.logger.debug(
                            f"[on_audio_activity] Resetting no_input_timer for call_id={effective_call_id} (segment processed)"
                        )
                        try:
                            # 直接 create_task を使用（async def 内なので）
                            task = asyncio.create_task(
                                self._start_no_input_timer(effective_call_id)
                            )
                            self.logger.debug(
                                f"[DEBUG_INIT] Scheduled no_input_timer task on segment processed for call_id={effective_call_id}, task={task}"
                            )
                        except Exception as e:
                            self.logger.exception(
                                f"[NO_INPUT] Failed to schedule no_input_timer on segment processed for call_id={effective_call_id}: {e}"
                            )

                if text_raw and intent != "IGNORE":
                    # ★ user_turn_index のインクリメントを非ストリーミングモードと統一
                    self.user_turn_index += 1
                    state_label = (intent or self.current_state).lower()
                    self.current_state = state_label
                    self._record_dialogue("ユーザー", text_raw)
                    self._append_console_log("user", text_raw, state_label)
                else:
                    state_label = self.current_state

                if reply_text:
                    self._record_dialogue("AI", reply_text)
                    self._append_console_log("ai", reply_text, self.current_state)

                if tts_audio_24k:
                    ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
                    chunk_size = 160
                    for i in range(0, len(ulaw_response), chunk_size):
                        self.tts_queue.append(ulaw_response[i : i + chunk_size])
                    self.logger.debug(">> TTS Queued")
                    self.is_speaking_tts = True

                if should_transfer:
                    self.logger.info(f">> TRANSFER REQUESTED to {OPERATOR_NUMBER}")
                    # 転送処理を実行
                    effective_call_id = self._get_effective_call_id()
                    self._handle_transfer(effective_call_id)

                # ログ出力
                if self.turn_rms_values:
                    rms_avg = sum(self.turn_rms_values) / len(self.turn_rms_values)
                else:
                    rms_avg = 0
                self.turn_rms_values = []

                # 実際の音声データ長から正確な秒数を算出
                duration = len(user_audio) / 2 / 16000.0
                text_norm = normalize_text(text_raw) if text_raw else ""

                # ★ turn_id管理: 非ストリーミングモードでのユーザー発話カウンター
                self.logger.debug(
                    f"TURN {self.turn_id}: RMS_AVG={rms_avg:.1f}, DURATION={duration:.2f}s, TEXT_RAW={text_raw}, TEXT_NORM={text_norm}, INTENT={intent}"
                )
                self.turn_id += 1

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


class ESLAudioReceiver:
    """Receive decoded audio frames from FreeSWITCH via ESL."""

    def __init__(self, call_id: str, uuid: str, gateway: "RealtimeGateway", logger):
        self.call_id = call_id
        self.uuid = uuid
        self.gateway = gateway
        self.logger = logger
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.conn = None

    def start(self) -> None:
        """Begin ESL event consumption in a background thread."""

        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        self.logger.info(
            "[ESL_AUDIO] Started for call_id=%s, uuid=%s", self.call_id, self.uuid
        )

    def _receive_loop(self) -> None:
        try:
            from libs.esl.ESL import ESLconnection

            self.conn = ESLconnection("127.0.0.1", "8021", "ClueCon")

            if not self.conn.connected():
                self.logger.error("[ESL_AUDIO] Failed to connect to FreeSWITCH ESL")
                return

            self.conn.events("plain", "CHANNEL_AUDIO")
            self.conn.filter("Unique-ID", self.uuid)

            self.logger.info("[ESL_AUDIO] Connected and subscribed to UUID=%s", self.uuid)

            while self.running:
                event = self.conn.recvEventTimed(100)

                if not event:
                    continue

                if event.getHeader("Event-Name") == "CHANNEL_AUDIO":
                    audio_data = event.getBody()
                    if audio_data:
                        self.gateway.handle_rtp_packet(self.call_id, audio_data)

        except Exception as exc:  # pragma: no cover - relies on FreeSWITCH runtime
            self.logger.error("[ESL_AUDIO] Exception: %s", exc)
            traceback.print_exc()

    def stop(self) -> None:
        """Stop ESL consumption and tear down resources."""

        self.running = False
        if self.conn:
            self.conn.disconnect()
        self.logger.info("[ESL_AUDIO] Stopped for call_id=%s", self.call_id)


class FreeswitchRTPMonitor:
    """Monitor FreeSWITCH outbound RTP and feed ASR once 002.wav ends."""

    def __init__(
        self,
        gateway: "RealtimeGateway",
        rtp_protocol_factory: Optional[Callable[[], asyncio.DatagramProtocol]] = None,
    ):
        self.gateway = gateway
        self.logger = gateway.logger
        self.freeswitch_rtp_port: Optional[int] = None
        self.monitor_sock: Optional[socket.socket] = None
        self.monitor_transport: Optional[asyncio.BaseTransport] = None
        self.asr_active = False
        self.capture_thread: Optional[threading.Thread] = None
        self.capture_running = False
        self.active_receivers: Dict[str, ESLAudioReceiver] = {}
        self._rtp_protocol_factory = rtp_protocol_factory

    # --- ESL monitoring helpers -------------------------------------------------
    def get_rtp_port_from_freeswitch(self) -> Optional[int]:
        """Return the current FreeSWITCH RTP port via info files or uuid_dump."""

        import re

        try:
            rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
            if rtp_info_files:
                candidate_port = None
                candidate_uuid = None
                candidate_mtime = 0.0
                for filepath in rtp_info_files:
                    try:
                        mtime = filepath.stat().st_mtime
                        with open(filepath, "r") as file_obj:
                            content = file_obj.read()
                        port = None
                        uuid = None
                        for line in content.splitlines():
                            if line.startswith("local="):
                                local_rtp = line.split("=", 1)[1].strip()
                                if ":" in local_rtp:
                                    port_str = local_rtp.split(":")[-1]
                                    try:
                                        port = int(port_str)
                                    except ValueError:
                                        self.logger.debug(
                                            "[FS_RTP_MONITOR] Failed to parse port in %s: %s",
                                            filepath,
                                            local_rtp,
                                        )
                                        port = None
                            elif line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()

                        if port and mtime >= candidate_mtime:
                            candidate_mtime = mtime
                            candidate_port = port
                            candidate_uuid = uuid
                            self.logger.info(
                                "[FS_RTP_MONITOR] Candidate RTP info: file=%s port=%s uuid=%s mtime=%s",
                                filepath,
                                port,
                                uuid,
                                mtime,
                            )
                    except Exception as exc:  # pragma: no cover - debug logging only
                        self.logger.debug(
                            "[FS_RTP_MONITOR] Error reading RTP info file %s: %s",
                            filepath,
                            exc,
                        )

                if candidate_port:
                    self.logger.info(
                        "[FS_RTP_MONITOR] Selected RTP port %s (from RTP info files, latest matched)",
                        candidate_port,
                    )
                    if candidate_uuid and hasattr(self.gateway, "call_uuid_map"):
                        if hasattr(self.gateway, "ai_core") and hasattr(
                            self.gateway.ai_core, "call_id"
                        ):
                            latest_call_id = self.gateway.ai_core.call_id
                            if latest_call_id:
                                try:
                                    pre_map = dict(self.gateway.call_uuid_map)
                                except Exception:
                                    pre_map = {}
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTER] Registering uuid=%s for call_id=%s current_map=%s",
                                    candidate_uuid,
                                    latest_call_id,
                                    pre_map,
                                )
                                self.gateway.call_uuid_map[latest_call_id] = candidate_uuid
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTERED] Updated map=%s",
                                    self.gateway.call_uuid_map,
                                )
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Mapped call_id=%s -> uuid=%s",
                                    latest_call_id,
                                    candidate_uuid,
                                )
                    return candidate_port
        except Exception as exc:  # pragma: no cover - diagnostics only
            self.logger.debug(
                "[FS_RTP_MONITOR] Error reading RTP info files (non-fatal): %s", exc
            )

        try:
            result = subprocess.run(
                ["fs_cli", "-x", "show", "channels"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "[FS_RTP_MONITOR] fs_cli failed: %s", result.stderr
                )
                return None

            lines = result.stdout.strip().split("\n")
            if len(lines) < 2 or lines[0].startswith("0 total"):
                return None

            uuid = None
            for line in lines[1:]:
                if line.strip() and not line.startswith("uuid,"):
                    parts = line.split(",")
                    if parts and parts[0].strip():
                        uuid = parts[0].strip()
                        break

            if not uuid:
                return None

            dump_result = subprocess.run(
                ["fs_cli", "-x", f"uuid_dump {uuid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if dump_result.returncode != 0:
                self.logger.warning(
                    "[FS_RTP_MONITOR] uuid_dump failed for %s (non-fatal): %s",
                    uuid,
                    dump_result.stderr,
                )
                return None

            for line in dump_result.stdout.splitlines():
                if "variable_rtp_local_port" in line:
                    try:
                        port = int(line.split("=")[-1].strip())
                        self.logger.info(
                            "[FS_RTP_MONITOR] Found FreeSWITCH RTP port: %s (from uuid_dump of %s)",
                            port,
                            uuid,
                        )
                        return port
                    except (ValueError, IndexError):
                        self.logger.warning(
                            "[FS_RTP_MONITOR] Failed to parse variable_rtp_local_port from line: %s",
                            line,
                        )

            import re

            port_matches = re.findall(
                r"(?:local_media_port|rtp_local_media_port)[:=]\s*(\d+)",
                dump_result.stdout,
            )
            if port_matches:
                port = int(port_matches[0])
                self.logger.info(
                    "[FS_RTP_MONITOR] Found FreeSWITCH RTP port: %s (from uuid_dump of %s, fallback format)",
                    port,
                    uuid,
                )
                return port

            self.logger.warning(
                "[FS_RTP_MONITOR] RTP port not found in uuid_dump output for %s",
                uuid,
            )
            self.logger.debug(
                "[FS_RTP_MONITOR] uuid_dump output: %s", dump_result.stdout[:500]
            )
            return None
        except Exception as exc:  # pragma: no cover - runtime diagnostics
            self.logger.warning(
                "[FS_RTP_MONITOR] Error getting RTP port (non-fatal): %s", exc
            )
            return None

    def update_uuid_mapping_for_call(self, call_id: str) -> Optional[str]:
        """Resolve FreeSWITCH UUID for a call_id and update the shared map."""

        import re

        uuid = None

        try:
            port_candidates = []
            try:
                if (
                    hasattr(self, "fs_rtp_monitor")
                    and getattr(self.fs_rtp_monitor, "freeswitch_rtp_port", None)
                ):
                    port_candidates.append(self.fs_rtp_monitor.freeswitch_rtp_port)
            except Exception:
                pass
            try:
                if hasattr(self, "rtp_port") and self.rtp_port:
                    port_candidates.append(self.rtp_port)
            except Exception:
                pass

            for port in port_candidates:
                try:
                    found_uuid = self._find_rtp_info_by_port(port)
                    if found_uuid:
                        uuid = found_uuid
                        self.logger.info(
                            "[UUID_UPDATE] Found UUID from RTP info file by port: uuid=%s call_id=%s port=%s",
                            uuid,
                            call_id,
                            port,
                        )
                        break
                except Exception as exc:  # pragma: no cover - diagnostics only
                    self.logger.debug(
                        "[UUID_UPDATE] Error during port-based RTP info search for port=%s: %s",
                        port,
                        exc,
                    )

            if not uuid:
                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    latest_file = max(rtp_info_files, key=lambda p: p.stat().st_mtime)
                    with open(latest_file, "r") as file_obj:
                        lines = file_obj.readlines()
                        for line in lines:
                            if line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from RTP info file: uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break
        except Exception as exc:  # pragma: no cover - diagnostics only
            self.logger.debug("[UUID_UPDATE] Error reading RTP info file: %s", exc)

        if not uuid:
            try:
                result = subprocess.run(
                    ["fs_cli", "-x", "show", "channels"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) >= 2 and not lines[0].startswith("0 total"):
                        header_line = lines[0] if lines[0].startswith("uuid,") else None
                        headers = header_line.split(",") if header_line else []
                        uuid_pattern = re.compile(
                            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                            re.IGNORECASE,
                        )
                        for line in lines[1:]:
                            if not line.strip() or line.startswith("uuid,"):
                                continue
                            parts = line.split(",")
                            if not parts or not parts[0].strip():
                                continue
                            candidate_uuid = parts[0].strip()
                            if not uuid_pattern.match(candidate_uuid):
                                continue
                            if call_id in line:
                                uuid = candidate_uuid
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from show channels (matched call_id): uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break

                        if not uuid:
                            for line in lines[1:]:
                                if not line.strip() or line.startswith("uuid,"):
                                    continue
                                parts = line.split(",")
                                if parts and parts[0].strip():
                                    candidate_uuid = parts[0].strip()
                                    if uuid_pattern.match(candidate_uuid):
                                        uuid = candidate_uuid
                                        self.logger.warning(
                                            "[UUID_UPDATE] Using first available UUID (call_id match failed): uuid=%s call_id=%s",
                                            uuid,
                                            call_id,
                                        )
                                        break
            except Exception as exc:  # pragma: no cover - diagnostic path
                self.logger.warning(
                    "[UUID_UPDATE] Error getting UUID from show channels: %s", exc
                )

        if uuid and hasattr(self.gateway, "call_uuid_map"):
            old_uuid = self.gateway.call_uuid_map.get(call_id)
            self.gateway.call_uuid_map[call_id] = uuid
            if old_uuid != uuid:
                self.logger.info(
                    "[UUID_UPDATE] Updated mapping: call_id=%s old_uuid=%s -> new_uuid=%s",
                    call_id,
                    old_uuid,
                    uuid,
                )
            else:
                self.logger.debug(
                    "[UUID_UPDATE] Mapping unchanged: call_id=%s uuid=%s", call_id, uuid
                )
            return uuid

        return None

    async def start_monitoring(self) -> None:
        uuid = getattr(self.gateway, "uuid", None)
        if not uuid:
            self.logger.error("[ESL_MONITOR] UUID not found in gateway")
            return

        call_id = f"in-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-4]}"
        self.logger.info(
            "[ESL_MONITOR] Starting ESL audio monitoring for call_id=%s, uuid=%s",
            call_id,
            uuid,
        )

        esl_receiver = ESLAudioReceiver(call_id, uuid, self.gateway, self.logger)
        esl_receiver.start()
        self.active_receivers[call_id] = esl_receiver

        if hasattr(self.gateway, "call_uuid_map"):
            self.gateway.call_uuid_map[call_id] = uuid

        self.logger.info("[ESL_MONITOR] ESL monitoring started for call_id=%s", call_id)

    async def _check_asr_enable_flag(self) -> None:
        check_count = 0
        while self.gateway.running:
            try:
                check_count += 1
                flag_files = list(Path("/tmp").glob("asr_enable_*.flag"))
                if check_count % 20 == 0 or flag_files:
                    self.logger.debug(
                        "[FS_RTP_MONITOR] Checking ASR enable flag (check #%s, found %s flag file(s), asr_active=%s)",
                        check_count,
                        len(flag_files),
                        self.asr_active,
                    )

                if flag_files:
                    flag_file = flag_files[0]
                    if not self.asr_active:
                        self.logger.info(
                            "[SAFE_DELAY] 初回アナウンス完了検知、ASR起動を3秒遅延させます"
                        )
                        self._schedule_asr_enable_after_initial_sequence()
                    try:
                        flag_file.unlink()
                        self.logger.info(
                            "[FS_RTP_MONITOR] Removed ASR enable flag: %s", flag_file
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "[FS_RTP_MONITOR] Failed to remove flag file: %s", exc
                        )
            except Exception as exc:
                self.logger.error(
                    "[FS_RTP_MONITOR] Error checking ASR enable flag: %s",
                    exc,
                    exc_info=True,
                )

            await asyncio.sleep(0.5)

    async def _monitor_rtp_info_files(self) -> None:
        while self.gateway.running:
            try:
                if self.freeswitch_rtp_port and self.monitor_sock:
                    await asyncio.sleep(5.0)
                    continue

                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    candidate_port = None
                    candidate_mtime = 0.0
                    for filepath in rtp_info_files:
                        try:
                            mtime = filepath.stat().st_mtime
                            with open(filepath, "r") as file_obj:
                                for line in file_obj:
                                    if line.startswith("local="):
                                        local_rtp = line.split("=", 1)[1].strip()
                                        if ":" in local_rtp:
                                            try:
                                                port_str = local_rtp.split(":")[-1]
                                                port = int(port_str)
                                            except ValueError:
                                                continue
                                            if mtime >= candidate_mtime:
                                                candidate_mtime = mtime
                                                candidate_port = port
                        except Exception as exc:
                            self.logger.debug(
                                "[FS_RTP_MONITOR] Error reading RTP info file %s: %s",
                                filepath,
                                exc,
                            )

                    port = candidate_port
                    if not port:
                        await asyncio.sleep(2.0)
                        continue

                    if port and port != self.freeswitch_rtp_port:
                        self.logger.info(
                            "[FS_RTP_MONITOR] Found RTP port %s from RTP info files, starting monitoring...",
                            port,
                        )
                        self.freeswitch_rtp_port = port
                        try:
                            if SCAPY_AVAILABLE:
                                self.capture_running = True
                                self.capture_thread = threading.Thread(
                                    target=self._pcap_capture_loop,
                                    args=(self.freeswitch_rtp_port,),
                                    daemon=True,
                                )
                                self.capture_thread.start()
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Started pcap monitoring for FreeSWITCH RTP port %s (from RTP info file)",
                                    self.freeswitch_rtp_port,
                                )
                            else:
                                loop = asyncio.get_running_loop()
                                self.monitor_sock = socket.socket(
                                    socket.AF_INET, socket.SOCK_DGRAM
                                )
                                self.monitor_sock.setsockopt(
                                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
                                )
                                self.monitor_sock.setsockopt(
                                    socket.SOL_SOCKET, socket.SO_REUSEPORT, 1
                                )
                                self.monitor_sock.bind(("0.0.0.0", self.freeswitch_rtp_port))
                                self.monitor_sock.setblocking(False)

                                if not self._rtp_protocol_factory:
                                    raise RuntimeError(
                                        "RTP protocol factory not provided for monitor socket"
                                    )

                                self.monitor_transport, _ = await loop.create_datagram_endpoint(
                                    self._rtp_protocol_factory,
                                    sock=self.monitor_sock,
                                )
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Started UDP socket monitoring for FreeSWITCH RTP port %s (from RTP info file)",
                                    self.freeswitch_rtp_port,
                                )
                        except Exception as exc:
                            self.logger.error(
                                "[FS_RTP_MONITOR] Failed to start monitoring port %s: %s",
                                port,
                                exc,
                                exc_info=True,
                            )
                            self.freeswitch_rtp_port = None

                await asyncio.sleep(2.0)
            except Exception as exc:
                self.logger.error(
                    "[FS_RTP_MONITOR] Error in _monitor_rtp_info_files: %s",
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(2.0)

    def enable_asr(self) -> None:
        if not self.asr_active:
            self.asr_active = True
            self.logger.info(
                "[FS_RTP_MONITOR] ASR enabled after 002.wav playback completion"
            )

            if self.gateway and hasattr(self.gateway, "ai_core") and self.gateway.ai_core:
                call_id = getattr(self.gateway, "call_id", None)
                try:
                    current_map = getattr(self.gateway, "call_uuid_map", {})
                except Exception:
                    current_map = {}
                self.logger.warning(
                    "[DEBUG_ENABLE_ASR_ENTRY] call_id=%s call_uuid_map=%s",
                    call_id,
                    current_map,
                )

                if not call_id and hasattr(self.gateway, "_get_effective_call_id"):
                    call_id = self.gateway._get_effective_call_id()
                    self.logger.warning(
                        "[DEBUG_ENABLE_ASR_EFFECTIVE] effective_call_id=%s", call_id
                    )

                if not call_id:
                    self.logger.error(
                        "[ENABLE_ASR_FAILED] Cannot enable ASR: call_id is None. This indicates RTP monitoring has not started yet."
                    )
                    return

                uuid = None
                if call_id and hasattr(self.gateway, "call_uuid_map"):
                    uuid = self.gateway.call_uuid_map.get(call_id)

                if call_id and not uuid:
                    self.logger.warning(
                        "[ENABLE_ASR_UUID_MISSING] call_id=%s not in map, attempting update_uuid_mapping",
                        call_id,
                    )
                    uuid = self.update_uuid_mapping_for_call(call_id)

                client_id = getattr(self.gateway, "client_id", "000") or "000"
                self.logger.warning(
                    "[DEBUG_ENABLE_ASR_UUID] call_id=%s uuid=%s", call_id, uuid
                )

                if not uuid:
                    self.logger.error(
                        "[ENABLE_ASR_FAILED] Cannot enable ASR: uuid not found for call_id=%s. RTP info file may not exist yet.",
                        call_id,
                    )
                    return

                try:
                    self.gateway.ai_core.enable_asr(uuid, client_id=client_id)
                    self.logger.info(
                        "[ENABLE_ASR_SUCCESS] ASR enabled: uuid=%s call_id=%s client_id=%s",
                        uuid,
                        call_id,
                        client_id,
                    )
                except Exception as exc:
                    self.logger.error(
                        "[FS_RTP_MONITOR] Failed to call AICore.enable_asr(): %s",
                        exc,
                        exc_info=True,
                    )
            else:
                self.logger.warning(
                    "[FS_RTP_MONITOR] Cannot call AICore.enable_asr(): gateway or ai_core not available"
                )

    def _schedule_asr_enable_after_initial_sequence(
        self, base_delay: float = 3.0, max_wait: float = 10.0
    ) -> None:
        if self.asr_active:
            return

        gateway_timer = getattr(self.gateway, "_asr_enable_timer", None)
        if gateway_timer:
            try:
                gateway_timer.cancel()
            except Exception:
                pass

        def _runner() -> None:
            waited = 0.0
            initial_done = getattr(self.gateway, "initial_sequence_completed", False)
            if not initial_done:
                self.logger.info(
                    "[SAFE_DELAY] 初回アナウンス完了待ちでASR起動を遅延 (max_wait=%ss, base_delay=%ss)",
                    max_wait,
                    base_delay,
                )
            while (
                not getattr(self.gateway, "initial_sequence_completed", False)
                and waited < max_wait
            ):
                time.sleep(0.5)
                waited += 0.5
            if base_delay > 0:
                time.sleep(base_delay)
                waited += base_delay
            try:
                self.enable_asr()
                self.logger.info(
                    "[SAFE_DELAY] ASR enabled (waited=%.1fs, initial_sequence_completed=%s)",
                    waited,
                    getattr(self.gateway, "initial_sequence_completed", False),
                )
            except Exception as exc:
                self.logger.error(
                    "[SAFE_DELAY] Failed to enable ASR: %s", exc, exc_info=True
                )

        timer = threading.Timer(0.0, _runner)
        timer.daemon = True
        timer.start()
        self.gateway._asr_enable_timer = timer

    def _pcap_capture_loop(self, port: int) -> None:
        print(f"DEBUG_TRACE: _pcap_capture_loop ENTERED port={port}", flush=True)
        try:
            self.logger.info("[FS_RTP_MONITOR] Starting pcap capture for port %s", port)
            filter_str = f"udp dst port {port}"
            try:
                self.logger.info("[PCAP_CONFIG] Starting capture with filter: '%s'", filter_str)
            except Exception:
                pass
            try:
                print(
                    f"DEBUG_PRINT: Starting pcap with filter='{filter_str}'",
                    flush=True,
                )
            except Exception:
                pass
            sniff(
                filter=filter_str,
                prn=self._process_captured_packet,
                stop_filter=lambda _: not self.capture_running,
                store=False,
            )
        except Exception as exc:  # pragma: no cover - requires scapy & network
            self.logger.error(
                "[FS_RTP_MONITOR] Error in pcap capture loop: %s",
                exc,
                exc_info=True,
            )
        finally:
            self.logger.info(
                "[FS_RTP_MONITOR] pcap capture loop ended for port %s", port
            )

    def _process_captured_packet(self, packet) -> None:
        if not hasattr(self, "_packet_debug_count"):
            self._packet_debug_count = 0
        self._packet_debug_count += 1
        if self._packet_debug_count % 50 == 1:
            print(
                f"DEBUG_TRACE: _process_captured_packet called count={self._packet_debug_count}",
                flush=True,
            )
        try:
            if IP in packet and UDP in packet:
                ip_layer = packet[IP]
                udp_layer = packet[UDP]
                src_ip = ip_layer.src
                src_port = udp_layer.sport
                rtp_data = bytes(udp_layer.payload)

                if len(rtp_data) > 0:
                    addr = (src_ip, src_port)
                    self.logger.debug(
                        "[RTP_RECV] Captured %s bytes from %s (pcap)",
                        len(rtp_data),
                        addr,
                    )
                    self.logger.info(
                        "[RTP_RECV_RAW] from=%s, len=%s (pcap)", addr, len(rtp_data)
                    )
                    if len(rtp_data) > 12:
                        audio_payload_size = len(rtp_data) - 12
                        self.logger.debug(
                            "[RTP_AUDIO] RTP packet: total=%s bytes, header=12 bytes, audio_payload=%s bytes (pcap)",
                            len(rtp_data),
                            audio_payload_size,
                        )
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.gateway.handle_rtp_packet(rtp_data, addr)
                        )
                        loop.close()
                    except Exception as exc:
                        self.logger.error(
                            "[FS_RTP_MONITOR] Error processing captured packet: %s",
                            exc,
                            exc_info=True,
                        )
        except Exception as exc:  # pragma: no cover - diagnostic path
            self.logger.error(
                "[FS_RTP_MONITOR] Error in _process_captured_packet: %s",
                exc,
                exc_info=True,
            )

    async def stop_monitoring(self) -> None:
        self.capture_running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=5.0)
        if self.monitor_transport:
            self.monitor_transport.close()
        if self.monitor_sock:
            self.monitor_sock.close()
        self.logger.info("[FS_RTP_MONITOR] Stopped monitoring FreeSWITCH RTP port")

    # ------------------------------------------------------------------
    def _find_rtp_info_by_port(self, rtp_port: int) -> Optional[str]:
        try:
            rtp_info_files = glob.glob("/tmp/rtp_info_*.txt")
            self.logger.debug(
                "[RTP_INFO_SEARCH] port=%s total_files=%s",
                rtp_port,
                len(rtp_info_files),
            )
            for filepath in rtp_info_files:
                try:
                    with open(filepath, "r") as file_obj:
                        content = file_obj.read()
                        if f":{rtp_port}" in content:
                            for line in content.split("\n"):
                                if line.startswith("uuid="):
                                    uuid = line.split("=", 1)[1].strip()
                                    self.logger.info(
                                        "[RTP_INFO_FOUND] port=%s file=%s uuid=%s",
                                        rtp_port,
                                        filepath,
                                        uuid,
                                    )
                                    return uuid
                except Exception as exc:
                    self.logger.debug(
                        "[RTP_INFO_READ_ERROR] file=%s error=%s",
                        filepath,
                        exc,
                    )
                    continue

            self.logger.warning(
                "[RTP_INFO_NOT_FOUND] No file found for port=%s searched_files=%s",
                rtp_port,
                len(rtp_info_files),
            )
            return None
        except Exception as exc:  # pragma: no cover - diagnostic path
            self.logger.exception(
                "[RTP_INFO_SEARCH_ERROR] port=%s error=%s",
                rtp_port,
                exc,
            )
            return None
