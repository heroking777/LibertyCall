"""Batch (non-streaming) ASR handling utilities."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from libertycall.gateway.audio.audio_utils import pcm24k_to_ulaw8k
from libertycall.gateway.common.text_utils import normalize_text

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.asr.asr_manager import GatewayASRManager


class ASRBatchHandler:
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def handle_batch_chunk(self, pcm16k_chunk: bytes, rms: int) -> None:
        manager = self.manager
        # --- バッファリング（非ストリーミングモード） ---
        # 初回シーケンス再生中は ASR をブロック（000→001→002 が必ず流れるように）
        if manager.initial_sequence_playing:
            manager.logger.debug(
                "[ASR_DEBUG] initial_sequence_playing=%s, streaming_enabled=%s, skipping audio_buffer (Batch ASR mode)",
                manager.initial_sequence_playing,
                manager.streaming_enabled,
            )
            return

        manager.audio_buffer.extend(pcm16k_chunk)
        manager.logger.debug(
            "[ASR_DEBUG] Added %s bytes to audio_buffer (total=%s bytes, streaming_enabled=%s)",
            len(pcm16k_chunk),
            len(manager.audio_buffer),
            manager.streaming_enabled,
        )

        # ★ 最初の音声パケット到達時刻を記録
        if manager.current_segment_start is None:
            manager.current_segment_start = time.time()

        # --- streaming_enabledに関係なくis_user_speakingを更新（Batch ASRモードでも動作するように） ---
        # BARGE_IN_THRESHOLDはTTS停止用の閾値、MIN_RMS_FOR_SPEECHはASR用の閾値として使用
        # ここでは、音声検出用のより低い閾値を使用（または常に更新）
        min_rms_for_speech = 80  # ASR用の最小RMS閾値（BARGE_IN_THRESHOLD=1000より低い）
        if rms > min_rms_for_speech:
            if not manager.is_user_speaking:
                manager.is_user_speaking = True
                manager.last_voice_time = time.time()
            manager.turn_rms_values.append(rms)
        elif rms <= min_rms_for_speech:
            # 無音が続く場合はis_user_speakingをFalseに（ただし、turn_rms_valuesには追加しない）
            # 既に蓄積されたRMS値は保持される
            pass

        # デバッグログ
        manager.logger.info(
            "[ASR_DEBUG] RMS=%.1f, is_user_speaking=%s, turn_rms_count=%s, streaming_enabled=%s",
            rms,
            manager.is_user_speaking,
            len(manager.turn_rms_values),
            manager.streaming_enabled,
        )

        # --- ストリーミングモードでは従来のバッファリング処理をスキップ ---
        if manager.streaming_enabled:
            return

        # --- ターミネート(区切り)判定（非ストリーミングモード） ---
        now = time.time()
        time_since_voice = now - manager.last_voice_time

        # セグメント経過時間を計算 (未開始なら0)
        segment_elapsed = 0.0
        if manager.current_segment_start is not None:
            segment_elapsed = now - manager.current_segment_start

        # ★ ハイブリッド条件
        # 1. 無音が SILENCE_DURATION 続いた
        # 2. または、話し始めてから MAX_SEGMENT_SEC 経過した
        should_cut = False

        # A. 無音タイムアウト
        if manager.is_user_speaking and time_since_voice > manager.SILENCE_DURATION:
            should_cut = True

        # B. 最大時間タイムアウト (音声がある場合のみ)
        elif len(manager.audio_buffer) > 0 and segment_elapsed > manager.MAX_SEGMENT_SEC:
            should_cut = True
            manager.logger.debug(">> MAX SEGMENT REACHED (%.2fs). Forcing cut.", segment_elapsed)

        if should_cut:
            # ノイズ除去: バッファが短すぎる場合は破棄
            if len(manager.audio_buffer) < manager.MIN_AUDIO_LEN:
                manager.logger.debug(
                    "[ASR_DEBUG] Segment too short: %s < %s, skipping",
                    len(manager.audio_buffer),
                    manager.MIN_AUDIO_LEN,
                )
                manager.audio_buffer = bytearray()
                manager.turn_rms_values = []
                manager.current_segment_start = None  # リセット
                return

            manager.logger.info(
                "[ASR_DEBUG] >> Processing segment... (buffer_size=%s, time_since_voice=%.2fs, segment_elapsed=%.2fs)",
                len(manager.audio_buffer),
                time_since_voice,
                segment_elapsed,
            )
            # セグメント処理開始時のturn_rms_valuesの状態をログ出力
            manager.logger.info(
                "[ASR_DEBUG] turn_rms_values: count=%s, values=%s",
                len(manager.turn_rms_values),
                manager.turn_rms_values[:10] if manager.turn_rms_values else "empty",
            )
            manager.is_user_speaking = False

            user_audio = bytes(manager.audio_buffer)

            # RMSベースのノイズゲート: 低RMSのセグメントはASRに送らない
            # RMS平均計算の直前にもログ追加
            manager.logger.info(
                "[ASR_DEBUG] Before RMS avg calculation: turn_rms_values count=%s",
                len(manager.turn_rms_values),
            )
            if manager.turn_rms_values:
                rms_avg = sum(manager.turn_rms_values) / len(manager.turn_rms_values)
            else:
                rms_avg = 0

            manager.logger.info(
                "[ASR_DEBUG] RMS check: rms_avg=%.1f, MIN_RMS_FOR_ASR=%s",
                rms_avg,
                manager.MIN_RMS_FOR_ASR,
            )
            if rms_avg < manager.MIN_RMS_FOR_ASR:
                manager.logger.info(
                    "[ASR_DEBUG] >> Segment skipped due to low RMS (rms_avg=%.1f < %s)",
                    rms_avg,
                    manager.MIN_RMS_FOR_ASR,
                )
                # セグメントを破棄してリセット
                manager.audio_buffer.clear()
                manager.turn_rms_values = []
                manager.current_segment_start = None
                manager.is_user_speaking = False
                return

            # 処理開始前にバッファとタイマーをリセット
            manager.audio_buffer = bytearray()
            manager.current_segment_start = None

            # AI処理実行
            manager.logger.info(
                "[ASR_DEBUG] Calling process_dialogue with %s bytes (streaming_enabled=%s, initial_sequence_playing=%s)",
                len(user_audio),
                manager.streaming_enabled,
                manager.initial_sequence_playing,
            )
            manager._ensure_console_session()
            (
                tts_audio_24k,
                should_transfer,
                text_raw,
                intent,
                reply_text,
            ) = manager.ai_core.process_dialogue(user_audio)
            manager.logger.info(
                "[ASR_DEBUG] process_dialogue returned: text_raw=%s, intent=%s, should_transfer=%s",
                text_raw,
                intent,
                should_transfer,
            )

            # 音声が検出された際に無音検知タイマーをリセット
            if text_raw and intent != "IGNORE":
                effective_call_id = manager._get_effective_call_id()
                if effective_call_id:
                    manager.logger.debug(
                        "[on_audio_activity] Resetting no_input_timer for call_id=%s (segment processed)",
                        effective_call_id,
                    )
                    try:
                        # 直接 create_task を使用（async def 内なので）
                        task = asyncio.create_task(
                            manager._start_no_input_timer(effective_call_id)
                        )
                        manager.logger.debug(
                            "[DEBUG_INIT] Scheduled no_input_timer task on segment processed for call_id=%s, task=%s",
                            effective_call_id,
                            task,
                        )
                    except Exception as exc:
                        manager.logger.exception(
                            "[NO_INPUT] Failed to schedule no_input_timer on segment processed for call_id=%s: %s",
                            effective_call_id,
                            exc,
                        )

            if text_raw and intent != "IGNORE":
                # ★ user_turn_index のインクリメントを非ストリーミングモードと統一
                manager.user_turn_index += 1
                state_label = (intent or manager.current_state).lower()
                manager.current_state = state_label
                manager._record_dialogue("ユーザー", text_raw)
                manager._append_console_log("user", text_raw, state_label)
            else:
                state_label = manager.current_state

            if reply_text:
                manager._record_dialogue("AI", reply_text)
                manager._append_console_log("ai", reply_text, manager.current_state)

            if tts_audio_24k:
                ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
                chunk_size = 160
                for i in range(0, len(ulaw_response), chunk_size):
                    manager.tts_queue.append(ulaw_response[i : i + chunk_size])
                manager.logger.debug(">> TTS Queued")
                manager.is_speaking_tts = True

            if should_transfer:
                manager.logger.info(">> TRANSFER REQUESTED to %s", manager.operator_number)
                # 転送処理を実行
                effective_call_id = manager._get_effective_call_id()
                manager._handle_transfer(effective_call_id)

            # ログ出力
            if manager.turn_rms_values:
                rms_avg = sum(manager.turn_rms_values) / len(manager.turn_rms_values)
            else:
                rms_avg = 0
            manager.turn_rms_values = []

            # 実際の音声データ長から正確な秒数を算出
            duration = len(user_audio) / 2 / 16000.0
            text_norm = normalize_text(text_raw) if text_raw else ""

            # ★ turn_id管理: 非ストリーミングモードでのユーザー発話カウンター
            manager.logger.debug(
                "TURN %s: RMS_AVG=%.1f, DURATION=%.2fs, TEXT_RAW=%s, TEXT_NORM=%s, INTENT=%s",
                manager.turn_id,
                rms_avg,
                duration,
                text_raw,
                text_norm,
                intent,
            )
            manager.turn_id += 1
