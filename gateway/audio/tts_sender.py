"""TTS queue management and sender loop."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from gateway.audio.audio_utils import pcm24k_to_ulaw8k

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.audio.playback_manager import GatewayPlaybackManager


_CURRENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CURRENT_DIR.parent.parent


class TTSSender:
    def __init__(self, manager: "GatewayPlaybackManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def _send_tts(
        self,
        call_id: str,
        reply_text: str,
        template_ids: list[str] | None = None,
        transfer_requested: bool = False,
    ) -> None:
        manager = self.manager
        if not reply_text and not template_ids:
            return

        # 会話状態を取得（ログ出力用）
        state = manager.ai_core._get_session_state(call_id)
        phase = state.phase
        template_id_str = ",".join(template_ids) if template_ids else "NONE"

        # 発信者番号を取得
        caller_number = getattr(manager.ai_core, "caller_number", None) or "-"
        if caller_number == "-" or not caller_number:
            caller_number = "未設定"

        # 会話トレースログを出力（発信者番号を含む）
        log_entry = (
            f"[{datetime.now().isoformat()}] CALLER={caller_number} PHASE={phase} "
            f"TEMPLATE={template_id_str} TEXT={reply_text}"
        )

        # コンソールに出力（発信者番号を表示）
        print(f"🗣️ [発信者: {caller_number}] {log_entry}")

        # ログファイルに追記
        conversation_log_path = Path(_PROJECT_ROOT) / "logs" / "conversation_trace.log"
        conversation_log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(conversation_log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as exc:
            self.logger.warning("Failed to write conversation trace log: %s", exc)

        # 重複TTS防止: 直前のTTSテキストと同じ場合はキューに追加しない
        tts_text_for_check = reply_text or (",".join(template_ids) if template_ids else "")

        # 初回TTS（初期アナウンス）の場合は常に送信（スキップしない）
        if not manager._last_tts_text:
            # 初回TTSとして記録して送信
            if tts_text_for_check:
                manager._last_tts_text = tts_text_for_check
                self.logger.info(
                    "[PLAY_TTS] dispatching (initial) text='%s...' to TTS queue for %s",
                    tts_text_for_check[:50],
                    call_id,
                )
            # 初回でもテキストがない場合はここで終了
            if not tts_text_for_check:
                return
        elif tts_text_for_check and manager._last_tts_text == tts_text_for_check:
            # 2回目以降の重複チェック
            self.logger.debug(
                "[TTS_QUEUE_SKIP] duplicate text ignored: '%s...'",
                tts_text_for_check[:30],
            )
            return
        else:
            # 新しいTTSテキストの場合
            if tts_text_for_check:
                manager._last_tts_text = tts_text_for_check

        # ChatGPT音声風: 文節単位再生のためのフラグ（短い応答やバックチャネルは一括再生）
        use_segmented_playback = reply_text and len(reply_text) > 10 and not template_ids

        # ChatGPT音声風: TTS生成を非同期タスクで実行（応答遅延を短縮）
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # イベントループが実行されていない場合は同期実行（フォールバック）
            self.logger.warning(
                "[TTS_ASYNC] Event loop not running, falling back to sync execution"
            )
            loop = None

        if template_ids and hasattr(manager.ai_core, "use_gemini_tts") and manager.ai_core.use_gemini_tts:
            # デバッグログ拡張: TTS_REPLY
            template_text = manager.ai_core._render_templates(template_ids)
            self.logger.info("[TTS_REPLY] \"%s\"", template_text)
            # template_ids ベースで TTS 合成（非同期タスクで実行）
            if loop:
                loop.create_task(
                    self._send_tts_async(
                        call_id,
                        template_ids=template_ids,
                        transfer_requested=transfer_requested,
                    )
                )
            else:
                # フォールバック: 同期実行
                tts_audio_24k = manager.ai_core._synthesize_template_sequence(template_ids)
                if tts_audio_24k:
                    ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
                    chunk_size = 160
                    for i in range(0, len(ulaw_response), chunk_size):
                        manager.tts_queue.append(ulaw_response[i : i + chunk_size])
                    manager.is_speaking_tts = True
                    manager._tts_sender_wakeup.set()
            return
        elif reply_text and hasattr(manager.ai_core, "use_gemini_tts") and manager.ai_core.use_gemini_tts:
            # デバッグログ拡張: TTS_REPLY
            self.logger.info("[TTS_REPLY] \"%s\"", reply_text)
            # 文節単位再生が有効な場合は非同期タスクで処理
            if use_segmented_playback:
                # 非同期タスクで文節単位再生を実行
                if loop:
                    loop.create_task(self._send_tts_segmented(call_id, reply_text))
                else:
                    # フォールバック: 同期実行（文節単位再生はスキップ）
                    tts_audio_24k = self._synthesize_text_sync(reply_text)
                    if tts_audio_24k:
                        ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
                        chunk_size = 160
                        for i in range(0, len(ulaw_response), chunk_size):
                            manager.tts_queue.append(ulaw_response[i : i + chunk_size])
                        manager.is_speaking_tts = True
                        manager._tts_sender_wakeup.set()
                return
            else:
                # 従来通り reply_text から TTS 合成（非同期タスクで実行）
                if loop:
                    loop.create_task(
                        self._send_tts_async(
                            call_id,
                            reply_text=reply_text,
                            transfer_requested=transfer_requested,
                        )
                    )
                else:
                    # フォールバック: 同期実行
                    tts_audio_24k = self._synthesize_text_sync(reply_text)
                    if tts_audio_24k:
                        ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
                        chunk_size = 160
                        for i in range(0, len(ulaw_response), chunk_size):
                            manager.tts_queue.append(ulaw_response[i : i + chunk_size])
                        manager.is_speaking_tts = True
                        manager._tts_sender_wakeup.set()
                return

        # リアルタイム更新: AI発話をConsoleに送信（非同期タスクで実行）
        try:
            effective_call_id = call_id or manager._get_effective_call_id()
            if effective_call_id:
                event = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "role": "AI",
                    "text": reply_text or (",".join(template_ids) if template_ids else ""),
                }
                # 非同期タスクとして実行（ブロックしない）
                asyncio.create_task(manager._push_console_update(effective_call_id, event=event))
        except Exception as exc:
            self.logger.warning("[REALTIME_PUSH] Failed to send AI speech event: %s", exc)

        # wait_time_afterの処理: テンプレート006の場合は1.8秒待機
        # 注意: 実際の待機処理は非同期で行うため、ここではフラグを設定
        if template_ids and "006" in template_ids:
            from gateway.common.text_utils import get_template_config

            template_config = get_template_config("006")
            if template_config and template_config.get("wait_time_after"):
                wait_time = template_config.get("wait_time_after", 1.8)
                # 非同期タスクで待機処理を実行（実際の実装は後で追加）
                self.logger.debug(
                    "TTS_WAIT: template 006 sent, will wait %ss for user response",
                    wait_time,
                )

    async def _send_tts_async(
        self,
        call_id: str,
        reply_text: str | None = None,
        template_ids: list[str] | None = None,
        transfer_requested: bool = False,
    ) -> None:
        manager = self.manager
        tts_audio_24k = None

        if template_ids and hasattr(manager.ai_core, "use_gemini_tts") and manager.ai_core.use_gemini_tts:
            # ChatGPT音声風: ThreadPoolExecutorで非同期TTS合成
            if hasattr(manager.ai_core, "tts_executor") and manager.ai_core.tts_executor:
                # 非同期でTTS合成を実行
                loop = asyncio.get_event_loop()
                tts_audio_24k = await loop.run_in_executor(
                    manager.ai_core.tts_executor,
                    manager.ai_core._synthesize_template_sequence,
                    template_ids,
                )
            else:
                # フォールバック: 同期実行
                tts_audio_24k = manager.ai_core._synthesize_template_sequence(template_ids)
        elif reply_text and hasattr(manager.ai_core, "use_gemini_tts") and manager.ai_core.use_gemini_tts:
            # ChatGPT音声風: ThreadPoolExecutorで非同期TTS合成
            if hasattr(manager.ai_core, "tts_executor") and manager.ai_core.tts_executor:
                # 非同期でTTS合成を実行
                loop = asyncio.get_event_loop()
                tts_audio_24k = await loop.run_in_executor(
                    manager.ai_core.tts_executor,
                    self._synthesize_text_sync,
                    reply_text,
                )
            else:
                # フォールバック: 同期実行
                tts_audio_24k = self._synthesize_text_sync(reply_text)

        # TTSキューに追加
        if tts_audio_24k:
            ulaw_response = pcm24k_to_ulaw8k(tts_audio_24k)
            chunk_size = 160
            for i in range(0, len(ulaw_response), chunk_size):
                manager.tts_queue.append(ulaw_response[i : i + chunk_size])
            self.logger.info(
                "TTS_SEND: call_id=%s text=%r queued=%s chunks",
                call_id,
                reply_text,
                len(ulaw_response) // chunk_size,
            )
            manager.is_speaking_tts = True

            # ChatGPT音声風: 即時送信トリガーを発火
            manager._tts_sender_wakeup.set()

            # 🔹 リアルタイム更新: AI発話をConsoleに送信
            try:
                effective_call_id = call_id or manager._get_effective_call_id()
                if effective_call_id:
                    event = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "role": "AI",
                        "text": reply_text or (",".join(template_ids) if template_ids else ""),
                    }
                    # 非同期タスクとして実行（ブロックしない）
                    asyncio.create_task(manager._push_console_update(effective_call_id, event=event))
            except Exception as exc:
                self.logger.warning(
                    "[REALTIME_PUSH] Failed to send AI speech event: %s",
                    exc,
                )

            # TTS送信完了時刻を記録（無音検出用）
            effective_call_id = call_id or manager._get_effective_call_id()
            if effective_call_id:
                # TTS送信完了を待つ非同期タスクを起動
                asyncio.create_task(
                    self._wait_for_tts_completion_and_update_time(
                        effective_call_id, len(ulaw_response)
                    )
                )

            # 転送要求フラグが立っている場合、TTS送信完了後に転送処理を開始
            if transfer_requested:
                self.logger.info(
                    "Transfer requested by AI core (handoff flag received). Will start transfer after TTS completion."
                )
                manager._pending_transfer_call_id = call_id
                asyncio.create_task(manager._wait_for_tts_and_transfer(call_id))

    def _synthesize_text_sync(self, text: str) -> Optional[bytes]:
        manager = self.manager
        try:
            # Gemini APIが有効でない場合はエラー
            if not hasattr(manager.ai_core, "use_gemini_tts") or not manager.ai_core.use_gemini_tts:
                self.logger.warning(
                    "[TTS] Gemini APIが無効です。text=%s...の音声合成をスキップします。",
                    text[:50],
                )
                return None

            # TTS設定からパラメータを取得
            tts_conf = getattr(manager.ai_core, "tts_config", {})
            speaking_rate = tts_conf.get("speaking_rate", 1.2)
            pitch = tts_conf.get("pitch", 0.0)
            return manager.ai_core._synthesize_text_with_gemini(text, speaking_rate, pitch)
        except Exception as exc:
            self.logger.exception("[TTS_SYNTHESIS_ERROR] text=%r error=%s", text, exc)
            return None

    async def _send_tts_segmented(self, call_id: str, reply_text: str) -> None:
        import re

        manager = self.manager
        self.logger.info("[TTS_SEGMENTED] call_id=%s text=%r", call_id, reply_text)
        manager.is_speaking_tts = True

        # 「。」「、」で分割（ただし、空のセグメントはスキップ）
        segments = re.split(r"([、。])", reply_text)
        # 区切り文字とテキストを結合（「、」「。」を前のセグメントに含める）
        combined_segments = []
        for i in range(0, len(segments), 2):
            if i + 1 < len(segments):
                combined_segments.append(segments[i] + segments[i + 1])
            elif segments[i].strip():
                combined_segments.append(segments[i])

        # 各文節を個別にTTS合成してキューに追加
        for segment in combined_segments:
            segment = segment.strip()
            if not segment:
                continue

            try:
                # ChatGPT音声風: ThreadPoolExecutorで非同期TTS合成
                if hasattr(manager.ai_core, "tts_executor") and manager.ai_core.tts_executor:
                    # 非同期でTTS合成を実行
                    loop = asyncio.get_event_loop()
                    segment_audio = await loop.run_in_executor(
                        manager.ai_core.tts_executor,
                        self._synthesize_segment_sync,
                        segment,
                    )
                else:
                    # フォールバック: 同期実行
                    segment_audio = self._synthesize_segment_sync(segment)

                if not segment_audio:
                    continue

                # μ-law変換してキューに追加
                ulaw_segment = pcm24k_to_ulaw8k(segment_audio)
                chunk_size = 160
                for i in range(0, len(ulaw_segment), chunk_size):
                    manager.tts_queue.append(ulaw_segment[i : i + chunk_size])

                self.logger.debug(
                    "[TTS_SEGMENT] call_id=%s segment=%r queued=%s chunks",
                    call_id,
                    segment,
                    len(ulaw_segment) // chunk_size,
                )

                # ChatGPT音声風: 文節ごとに即時送信トリガーを発火
                manager._tts_sender_wakeup.set()

                # 文節間に0.2秒ポーズを挿入（最後の文節以外）
                if segment != combined_segments[-1]:
                    await asyncio.sleep(0.2)

            except Exception as exc:
                self.logger.exception(
                    "[TTS_SEGMENT_ERROR] call_id=%s segment=%r error=%s",
                    call_id,
                    segment,
                    exc,
                )

        self.logger.info(
            "[TTS_SEGMENTED_COMPLETE] call_id=%s segments=%s",
            call_id,
            len(combined_segments),
        )

    def _synthesize_segment_sync(self, segment: str) -> Optional[bytes]:
        manager = self.manager
        try:
            # Gemini APIが有効でない場合はエラー
            if not hasattr(manager.ai_core, "use_gemini_tts") or not manager.ai_core.use_gemini_tts:
                self.logger.warning(
                    "[TTS] Gemini APIが無効です。segment=%s...の音声合成をスキップします。",
                    segment[:50],
                )
                return None

            # TTS設定からパラメータを取得
            tts_conf = getattr(manager.ai_core, "tts_config", {})
            speaking_rate = tts_conf.get("speaking_rate", 1.2)
            pitch = tts_conf.get("pitch", 0.0)
            return manager.ai_core._synthesize_text_with_gemini(segment, speaking_rate, pitch)
        except Exception as exc:
            self.logger.exception(
                "[TTS_SYNTHESIS_ERROR] segment=%r error=%s",
                segment,
                exc,
            )
            return None

    async def _wait_for_tts_completion_and_update_time(
        self, call_id: str, tts_audio_length: int
    ) -> None:
        manager = self.manager
        # TTS送信完了を待つ（is_speaking_tts が False になるまで）
        start_time = time.time()
        while manager.running and manager.is_speaking_tts:
            if time.time() - start_time > 30.0:  # 最大30秒待つ
                break
            await asyncio.sleep(0.1)

        # 追加の待機: キューが完全に空になるまで待つ
        queue_wait_start = time.time()
        while manager.running and len(manager.tts_queue) > 0:
            if time.time() - queue_wait_start > 2.0:  # 最大2秒待つ
                break
            await asyncio.sleep(0.05)

        # TTS送信完了時刻を記録（time.monotonic()で統一）
        now = time.monotonic()
        manager._last_tts_end_time[call_id] = now
        self.logger.debug(
            "[NO_INPUT] TTS completion recorded: call_id=%s time=%.2f",
            call_id,
            now,
        )

    async def _tts_sender_loop(self) -> None:
        manager = self.manager
        self.logger.debug("TTS Sender loop started.")
        consecutive_skips = 0
        while manager.running:
            # ChatGPT音声風: wakeupイベントがセットされていたら即flush
            if manager._tts_sender_wakeup.is_set():
                await self._flush_tts_queue()
                manager._tts_sender_wakeup.clear()

            if manager.tts_queue and manager.rtp_transport:
                # FreeSWITCH双方向化: 受信元アドレス（rtp_peer）に送信
                # rtp_peerが設定されていない場合は警告を出してスキップ
                # （rtp_peerは最初のRTPパケット受信時に自動設定される）
                if manager.rtp_peer:
                    rtp_dest = manager.rtp_peer
                else:
                    # rtp_peerが未設定の場合は送信をスキップ（最初のRTPパケット受信待ち）
                    if consecutive_skips == 0:
                        self.logger.warning(
                            "[TTS_SENDER] rtp_peer not set yet, waiting for first RTP packet..."
                        )
                    consecutive_skips += 1
                    await asyncio.sleep(0.02)
                    continue
                try:
                    payload = manager.tts_queue.popleft()
                    packet = manager.rtp_builder.build_packet(payload)
                    manager.rtp_transport.sendto(packet, rtp_dest)
                    # 実際に送信したタイミングでログ出力（運用ログ整備）
                    payload_type = packet[1] & 0x7F
                    self.logger.debug(
                        "[TTS_QUEUE_SEND] sent RTP packet to %s, queue_len=%s, payload_type=%s",
                        rtp_dest,
                        len(manager.tts_queue),
                        payload_type,
                    )
                    # デバッグログ拡張: RTP_SENT（最初のパケットのみ）
                    if not hasattr(manager, "_rtp_sent_logged"):
                        self.logger.info("[RTP_SENT] %s", rtp_dest)
                        manager._rtp_sent_logged = True
                    consecutive_skips = 0  # リセット
                except Exception as exc:
                    self.logger.error("TTS sender failed: %s", exc, exc_info=True)
            else:
                # キューが空 or 停止状態
                if not manager.tts_queue:
                    manager.is_speaking_tts = False
                    consecutive_skips = 0
                    # 初回シーケンス再生が完了したらフラグをリセット
                    if manager.initial_sequence_playing:
                        # スレッドスイッチを確保してからフラグを変更（非同期ループの確実な実行のため）
                        await asyncio.sleep(0.01)
                        manager.initial_sequence_playing = False
                        manager.initial_sequence_completed = True
                        manager.initial_sequence_completed_time = time.time()
                        self.logger.info(
                            "[INITIAL_SEQUENCE] OFF: initial_sequence_playing=False -> completed=True (ASR enable allowed)"
                        )

            await asyncio.sleep(0.02)  # CPU負荷を軽減（送信間隔を20ms空ける）

    async def _flush_tts_queue(self) -> None:
        """
        ChatGPT音声風: TTSキューを即座に送信（wakeupイベント用）
        """
        manager = self.manager
        if not manager.tts_queue or not manager.rtp_transport or not manager.rtp_peer:
            return

        # キュー内のすべてのパケットを即座に送信
        sent_count = 0
        while manager.tts_queue and manager.running:
            try:
                payload = manager.tts_queue.popleft()
                packet = manager.rtp_builder.build_packet(payload)
                manager.rtp_transport.sendto(packet, manager.rtp_peer)
                sent_count += 1
            except Exception as exc:
                self.logger.error(
                    "[TTS_FLUSH_ERROR] Failed to send packet: %s",
                    exc,
                    exc_info=True,
                )
                break

        if sent_count > 0:
            self.logger.debug("[TTS_FLUSH] Flushed %s packets from queue", sent_count)
