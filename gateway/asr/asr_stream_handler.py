"""Streaming ASR handling utilities."""
from __future__ import annotations

import asyncio
import audioop
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from gateway.audio.audio_utils import pcm24k_to_ulaw8k
from gateway.common.text_utils import get_response_template, normalize_text
from gateway.transcript.transcript_normalizer import normalize_transcript

from .google_asr import GoogleASR

try:  # pragma: no cover - optional dependency
    from asr_handler import get_or_create_handler
except ImportError:  # pragma: no cover - optional dependency
    get_or_create_handler = None

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.asr.asr_manager import GatewayASRManager


class ASRStreamHandler:
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    @staticmethod
    def handle_new_audio(core, call_id: str, pcm16k_bytes: bytes) -> None:
        core.logger.debug(
            "[AI_CORE] on_new_audio called. Len=%s call_id=%s",
            len(pcm16k_bytes),
            call_id,
        )

        if not core.streaming_enabled:
            return

        if call_id not in core._call_started_calls:
            core.logger.warning(
                "[ASR_RECOVERY] call_id=%s not in _call_started_calls but receiving audio. Auto-registering.",
                call_id,
            )
            core._call_started_calls.add(call_id)

        if core.asr_provider == "google":
            core.logger.debug(
                "AICore: on_new_audio (provider=google) call_id=%s len=%s bytes",
                call_id,
                len(pcm16k_bytes),
            )

            if not hasattr(core, "asr_instances"):
                core.asr_instances = {}
                core.asr_lock = threading.Lock()
                core._phrase_hints = []

            asr_instance = None
            newly_created = False
            with core.asr_lock:
                print(
                    f"[ASR_LOCK_ACQUIRED] call_id={call_id}, current_instances={list(core.asr_instances.keys())}",
                    flush=True,
                )

                if call_id not in core.asr_instances:
                    caller_stack = traceback.extract_stack()
                    caller_info = (
                        f"{caller_stack[-3].filename}:{caller_stack[-3].lineno} in {caller_stack[-3].name}"
                    )
                    print(
                        f"[ASR_INSTANCE_CREATE] Creating new GoogleASR for call_id={call_id}",
                        flush=True,
                    )
                    print(
                        f"[ASR_CREATE_CALLER] call_id={call_id}, caller={caller_info}",
                        flush=True,
                    )
                    core.logger.info(
                        "[ASR_INSTANCE_CREATE] Creating new GoogleASR for call_id=%s",
                        call_id,
                    )
                    try:
                        new_asr = GoogleASR(
                            language_code="ja-JP",
                            sample_rate=16000,  # FreeSWITCHは16kHzで送信
                            phrase_hints=getattr(core, "_phrase_hints", []),
                            ai_core=core,
                            error_callback=core._on_asr_error,
                        )
                        core.asr_instances[call_id] = new_asr
                        newly_created = True
                        print(
                            f"[ASR_INSTANCE_CREATED] call_id={call_id}, total_instances={len(core.asr_instances)}",
                            flush=True,
                        )
                        core.logger.info(
                            "[ASR_INSTANCE_CREATED] call_id=%s, total_instances=%s",
                            call_id,
                            len(core.asr_instances),
                        )
                    except Exception as exc:
                        core.logger.error(
                            "[ASR_INSTANCE_CREATE_FAILED] call_id=%s: %s",
                            call_id,
                            exc,
                            exc_info=True,
                        )
                        print(
                            f"[ASR_INSTANCE_CREATE_FAILED] call_id={call_id}: {exc}",
                            flush=True,
                        )
                        return
                else:
                    print(
                        f"[ASR_INSTANCE_REUSE] call_id={call_id} already exists",
                        flush=True,
                    )

                asr_instance = core.asr_instances.get(call_id)

            if newly_created and asr_instance is not None:
                asr_instance._start_stream_worker(call_id)
                max_wait = 0.5
                wait_interval = 0.02
                elapsed = 0.0
                print(
                    f"[ASR_STREAM_WAIT] call_id={call_id} Waiting for stream thread to start...",
                    flush=True,
                )
                while elapsed < max_wait:
                    if (
                        asr_instance._stream_thread is not None
                        and asr_instance._stream_thread.is_alive()
                    ):
                        break
                    time.sleep(wait_interval)
                    elapsed += wait_interval

                stream_ready = (
                    asr_instance._stream_thread is not None
                    and asr_instance._stream_thread.is_alive()
                )
                if stream_ready:
                    print(
                        f"[ASR_STREAM_READY] call_id={call_id} Stream thread ready after {elapsed:.3f}s",
                        flush=True,
                    )
                    core.logger.info(
                        "[ASR_STREAM_READY] call_id=%s Stream thread ready after %.3fs",
                        call_id,
                        elapsed,
                    )
                else:
                    print(
                        f"[ASR_STREAM_TIMEOUT] call_id={call_id} Stream thread not ready after {elapsed:.3f}s",
                        flush=True,
                    )
                    core.logger.warning(
                        "[ASR_STREAM_TIMEOUT] call_id=%s Stream thread not ready after %.3fs",
                        call_id,
                        elapsed,
                    )

            if asr_instance is not None:
                try:
                    core.logger.warning(
                        "[ON_NEW_AUDIO_FEED] About to call feed_audio for call_id=%s, chunk_size=%s",
                        call_id,
                        len(pcm16k_bytes),
                    )
                    asr_instance.feed_audio(call_id, pcm16k_bytes)
                    core.logger.warning(
                        "[ON_NEW_AUDIO_FEED_DONE] feed_audio completed for call_id=%s",
                        call_id,
                    )
                except Exception as exc:
                    core.logger.error(
                        "AICore: GoogleASR.feed_audio 失敗 (call_id=%s): %s",
                        call_id,
                        exc,
                        exc_info=True,
                    )
                    core.logger.info(
                        "ASR_GOOGLE_ERROR: feed_audio失敗 (call_id=%s): %s",
                        call_id,
                        exc,
                    )
        else:
            core.asr_model.feed(call_id, pcm16k_bytes)  # type: ignore[union-attr]

    def handle_streaming_chunk(self, pcm16k_chunk: bytes, rms: int) -> bool:
        manager = self.manager
        if not manager.streaming_enabled:
            return False

        # call_idがNoneでも一時的なIDで処理（WebSocket initが来る前でも動作するように）
        effective_call_id = manager._get_effective_call_id()

        # 再生中はASRに送らない（システム再生音の混入を防ぐ）
        if (
            hasattr(manager.ai_core, "is_playing")
            and manager.ai_core.is_playing.get(effective_call_id, False)
        ):
            return True

        # 通常のストリーミング処理
        manager._stream_chunk_counter += 1

        # 前回からの経過時間を計算
        current_time = time.time()
        dt_ms = (current_time - manager._last_feed_time) * 1000
        manager._last_feed_time = current_time

        # 【小出し送信】100ms（3200 bytes）ごとに刻んでリアルタイムにストリームへ流し込む
        if not hasattr(manager, '_chunk_buffer'):
            manager._chunk_buffer = bytearray()
            manager._last_chunk_time = current_time
        
        # 現在のチャンクをバッファに追加
        manager._chunk_buffer.extend(pcm16k_chunk)
        buffer_duration_ms = (current_time - manager._last_chunk_time) * 1000
        
        self.logger.info(f"[CHUNKING_DEBUG] buffer_size={len(manager._chunk_buffer)} bytes, duration={buffer_duration_ms:.1f}ms")
        
        # 100ms以上溜まったら送信（16kHz * 2bytes * 0.1s = 3200 bytes）
        if buffer_duration_ms >= 100 or len(manager._chunk_buffer) >= 3200:
            # バッファから送信データを取得
            chunked_data = bytes(manager._chunk_buffer[:3200])  # 最初の3200 bytesのみ
            manager._chunk_buffer = manager._chunk_buffer[3200:]  # 残りを保持
            manager._last_chunk_time = current_time
            
            self.logger.info(f"[CHUNK_SEND] Sending chunked data: {len(chunked_data)} bytes, {buffer_duration_ms:.1f}ms")
            
            # チャンクしたデータで元の処理を継続
            pcm16k_chunk = chunked_data
        else:
            # まだバッファが溜まっていない場合は送信しない
            self.logger.debug(f"[CHUNK_WAIT] Waiting for more data: {buffer_duration_ms:.1f}ms < 100ms")
            return True

        # RMS記録（統計用）
        if manager.is_user_speaking:
            manager.turn_rms_values.append(rms)

        # ログ出力（頻度を下げる：10チャンクに1回、最初のチャンク、またはRMS閾値超過時）
        should_log_info = (
            manager._stream_chunk_counter % 10 == 0
            or manager._stream_chunk_counter == 1
            or rms > manager.BARGE_IN_THRESHOLD
        )
        if should_log_info:
            self.logger.info(
                "STREAMING_FEED: idx=%s dt=%.1fms call_id=%s len=%s rms=%s",
                manager._stream_chunk_counter,
                dt_ms,
                effective_call_id,
                len(pcm16k_chunk),
                rms,
            )
        else:
            self.logger.debug(
                "STREAMING_FEED: idx=%s dt=%.1fms",
                manager._stream_chunk_counter,
                dt_ms,
            )

        # 【診断用】16kHz変換後、on_new_audio呼び出し直前のRMS値確認
        try:
            rms_16k = audioop.rms(pcm16k_chunk, 2)
            if not hasattr(manager, "_rms_16k_debug_count"):
                manager._rms_16k_debug_count = 0
            if manager._rms_16k_debug_count < 50:
                import struct

                samples_16k = struct.unpack(
                    f"{len(pcm16k_chunk)//2}h", pcm16k_chunk
                )
                max_sample_16k = (
                    max(abs(s) for s in samples_16k) if samples_16k else 0
                )
                self.logger.info(
                    "[RTP_AUDIO_RMS] call_id=%s stage=16khz_resample len=%s rms=%s max_amplitude=%s",
                    effective_call_id,
                    len(pcm16k_chunk),
                    rms_16k,
                    max_sample_16k,
                )
                # 最初の5サンプルをログ出力
                if len(samples_16k) >= 5:
                    self.logger.info(
                        "[RTP_AUDIO_SAMPLES] call_id=%s stage=16khz first_5_samples=%s",
                        effective_call_id,
                        samples_16k[:5],
                    )
                manager._rms_16k_debug_count += 1
            else:
                # 50回以降はRMS値のみ（頻度を下げる：10回に1回）
                if manager._rms_16k_debug_count % 10 == 0:
                    self.logger.info(
                        "[RTP_AUDIO_RMS] call_id=%s stage=16khz_resample rms=%s",
                        effective_call_id,
                        rms_16k,
                    )
                manager._rms_16k_debug_count += 1
        except Exception as exc:
            self.logger.debug("[RTP_AUDIO_RMS] Failed to calculate RMS: %s", exc)

        # 【追加】ASR送信前のRMSログ（間引き出力）
        try:
            if hasattr(manager, "_stream_chunk_counter"):
                # 間引き: 50チャンクに1回ログ
                if manager._stream_chunk_counter % 50 == 0:
                    try:
                        asr_rms = audioop.rms(pcm16k_chunk, 2)
                    except Exception:
                        asr_rms = -1
                    self.logger.info(
                        "[ASR_INPUT_RMS] call_id=%s rms=%s chunk_idx=%s",
                        effective_call_id,
                        asr_rms,
                        manager._stream_chunk_counter,
                    )
                    # 【強制出力】標準出力に出して即時確認（loggerに依存しない）
                    try:
                        print(
                            "DEBUG_PRINT: call_id=%s ASR_INPUT_RMS=%s chunk_idx=%s"
                            % (effective_call_id, asr_rms, manager._stream_chunk_counter),
                            flush=True,
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        # ASRへ送信（エラーハンドリング付き）
        try:
            self.logger.info(
                "[ASR_DEBUG] Calling on_new_audio with %s bytes (streaming_enabled=True, call_id=%s)",
                len(pcm16k_chunk),
                effective_call_id,
            )
            manager.ai_core.on_new_audio(effective_call_id, pcm16k_chunk)
        except Exception as exc:
            self.logger.error("ASR feed error: %s", exc, exc_info=True)

        # Google Streaming ASRへ音声を送信
        # デバッグ: ASRハンドラーの状態を確認
        self.logger.debug(
            "[ASR_DEBUG] asr_handler_enabled=%s, get_or_create_handler=%s",
            manager.asr_handler_enabled,
            get_or_create_handler is not None,
        )

        if manager.asr_handler_enabled and get_or_create_handler:
            try:
                # get_or_create_handlerで取得（プロセス間で共有されないため、自プロセス内で作成）
                handler = get_or_create_handler(effective_call_id)
                self.logger.debug(
                    "[ASR_DEBUG] handler=%s, handler.asr=%s",
                    handler,
                    handler.asr if handler else None,
                )

                # 初回のみon_incoming_call()を呼ぶ（asrがNoneの場合）
                if handler and handler.asr is None:
                    self.logger.info(
                        "[ASR_HOOK] Calling on_incoming_call() for call_id=%s",
                        effective_call_id,
                    )
                    handler.on_incoming_call()
                    self.logger.info(
                        "[ASR_HOOK] ASR handler on_incoming_call() executed for call_id=%s",
                        effective_call_id,
                    )

                # 音声データを送信
                if handler and hasattr(handler, "on_audio_chunk"):
                    handler.on_audio_chunk(pcm16k_chunk)
                    self.logger.info(
                        "[ASR_DEBUG] Audio chunk sent to ASR handler (len=%s)",
                        len(pcm16k_chunk),
                    )
            except Exception as exc:
                self.logger.error("ASR handler feed error: %s", exc, exc_info=True)
        else:
            self.logger.debug(
                "[ASR_DEBUG] ASR handler disabled or not available (enabled=%s, available=%s)",
                manager.asr_handler_enabled,
                get_or_create_handler is not None,
            )

        return True

    def handle_asr_final(self, call_uuid: str, final_text: str, confidence: float, source: str = "unknown") -> None:
        """
        ASR final結果を既存返答ルールへ接着する薄いラッパー
        
        Args:
            call_uuid: FreeSWITCH UUID（またはcall_id）
            final_text: ASR最終テキスト
            confidence: 信頼度
            source: ASRプロバイダ名（例: "google"）
        """
        manager = self.manager
        
        # 空振り防止
        if not final_text or not final_text.strip():
            manager.logger.debug("[ASR_FINAL_IN] Skipped empty text (uuid=%s source=%s)", call_uuid, source)
            return
        
        # UUID照合用にeffective_call_idを取得してログ
        effective_call_id = manager._get_effective_call_id()
        manager.logger.info(
            "[ASR_FINAL_IN] uuid_in=%s effective_call_id=%s text=\"%s\" conf=%.3f source=%s",
            call_uuid,
            effective_call_id,
            final_text[:100],
            confidence,
            source
        )
        
        # 既存handle_asr_resultを呼び出す（audio_duration等は0で仮）
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            loop.create_task(self.handle_asr_result(final_text, 0.0, 0.0, 0.0))
        except RuntimeError:
            # イベントループ未取得時はsync実行
            import asyncio
            asyncio.run(self.handle_asr_result(final_text, 0.0, 0.0, 0.0))

    async def handle_asr_result(
        self, text: str, audio_duration: float, inference_time: float, end_to_text_delay: float
    ) -> None:
        manager = self.manager
        # 初回シーケンス再生中は ASR/TTS をブロック（000→001→002 が必ず流れるように）
        if manager.initial_sequence_playing:
            return

        if not text:
            return

        # 幻聴フィルター（AICoreのロジックを再利用）
        if manager.ai_core._is_hallucination(text):
            manager.logger.debug(">> Ignored hallucination (noise)")
            return

        # ユーザー発話のturn_indexをインクリメント
        manager.user_turn_index += 1

        # 通話開始からの経過時間を計算
        elapsed_from_call_start_ms = 0
        if manager.call_start_time is not None:
            elapsed_from_call_start_ms = int((time.time() - manager.call_start_time) * 1000)

        # テキスト正規化（「もしもし」補正など）
        effective_call_id = manager._get_effective_call_id()
        raw_text = text
        normalized_text, rule_applied = normalize_transcript(
            effective_call_id,
            raw_text,
            manager.user_turn_index,
            elapsed_from_call_start_ms,
        )

        # ログ出力（常にINFOで出力）
        manager.logger.info("ASR_RAW: '%s'", raw_text)
        if rule_applied:
            manager.logger.info(
                "ASR_NORMALIZED: '%s' (rule=%s)",
                normalized_text,
                rule_applied,
            )
        else:
            manager.logger.info("ASR_NORMALIZED: '%s' (rule=NONE)", normalized_text)

        # 以降は正規化されたテキストを使用
        text = normalized_text

        # ASR反応を検出したらフラグファイルを作成（Luaスクリプト用）
        if effective_call_id and text.strip():
            try:
                flag_file = Path(f"/tmp/asr_response_{effective_call_id}.flag")
                flag_file.touch()
                manager.logger.info(
                    "[ASR_RESPONSE] Created ASR response flag: %s (text: %s)",
                    flag_file,
                    text[:50],
                )
            except Exception as exc:
                manager.logger.warning(
                    "[ASR_RESPONSE] Failed to create ASR response flag: %s",
                    exc,
                )

        # 🔹 リアルタイム更新: ユーザー発話をConsoleに送信
        if effective_call_id and text.strip():
            try:
                event = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "role": "USER",
                    "text": text,
                }
                # 非同期タスクとして実行（ブロックしない）
                asyncio.create_task(manager._push_console_update(effective_call_id, event=event))
            except Exception as exc:
                manager.logger.warning(
                    "[REALTIME_PUSH] Failed to send user speech event: %s",
                    exc,
                )

        # ユーザー発話時刻を記録（無音検出用、time.monotonic()で統一）
        now = time.monotonic()
        manager._last_user_input_time[effective_call_id] = now
        # no_input_streakをリセット（ユーザーが発話したので）
        state = manager.ai_core._get_session_state(effective_call_id)
        caller_number = getattr(manager.ai_core, "caller_number", None) or "未設定"

        # 【デバッグ】音声アクティビティ検知
        detected_speech = bool(text and text.strip())
        manager.logger.debug(
            "[on_audio_activity] call_id=%s, detected_speech=%s, text=%s, resetting_timer",
            effective_call_id,
            detected_speech,
            text[:30] if text else "None",
        )

        # 音声が受信された際に無音検知タイマーをリセットして再スケジュール
        if detected_speech:
            manager.logger.debug(
                "[on_audio_activity] Resetting no_input_timer for call_id=%s",
                effective_call_id,
            )
            await manager._start_no_input_timer(effective_call_id)

        if text.strip() in manager.NO_INPUT_SILENT_PHRASES:
            manager.logger.info(
                "[NO_INPUT] call_id=%s caller=%s reset by filler '%s'",
                effective_call_id,
                caller_number,
                text.strip(),
            )
            state.no_input_streak = 0
            manager._no_input_elapsed[effective_call_id] = 0.0
        elif state.no_input_streak > 0:
            manager.logger.info(
                "[NO_INPUT] call_id=%s caller=%s streak reset (user input detected: %s)",
                effective_call_id,
                caller_number,
                text[:30],
            )
            state.no_input_streak = 0
            manager._no_input_elapsed[effective_call_id] = 0.0

        # 状態更新（応答はon_transcript経由のgenerate_replyで処理）
        manager._record_dialogue("ユーザー", text)
        manager._append_console_log("user", text, manager.current_state)

        # ログ出力（発話長、推論時間、遅延時間）
        text_norm = normalize_text(text) if text else ""
        manager.logger.info(
            "STREAMING_TURN %s: audio=%.2fs / infer=%.3fs / delay=%.3fs -> '%s' (intent=%s)",
            manager.turn_id,
            audio_duration,
            inference_time,
            end_to_text_delay,
            text_norm,
            intent,
        )
        manager.turn_id += 1
