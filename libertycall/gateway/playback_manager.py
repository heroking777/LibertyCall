"""Playback/TTS manager extracted from realtime_gateway."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from libertycall.gateway.tts_sender import TTSSender
from libertycall.gateway.playback_controller import PlaybackController
from libertycall.gateway.playback_handler import PlaybackHandler
from libertycall.gateway.playback_sequencer import PlaybackSequencer

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


class GatewayPlaybackManager:
    """Move playback/TTS logic out of RealtimeGateway."""

    def __init__(self, gateway: "RealtimeGateway") -> None:
        super().__setattr__("gateway", gateway)
        super().__setattr__("logger", gateway.logger)
        super().__setattr__("tts_sender", TTSSender(self))
        super().__setattr__("controller", PlaybackController(self))
        super().__setattr__("handler", PlaybackHandler(self))
        super().__setattr__("sequencer", PlaybackSequencer(self))

    def __getattr__(self, name: str):
        return getattr(self.gateway, name)

    def __setattr__(self, name: str, value) -> None:
        if name in {"gateway", "logger"}:
            super().__setattr__(name, value)
        else:
            setattr(self.gateway, name, value)

    def _handle_playback(self, call_id: str, audio_file: str) -> None:
        self.handler.handle_playback(call_id, audio_file)

    def _send_tts(
        self,
        call_id: str,
        reply_text: str,
        template_ids: list[str] | None = None,
        transfer_requested: bool = False,
    ) -> None:
        self.tts_sender._send_tts(
            call_id,
            reply_text,
            template_ids=template_ids,
            transfer_requested=transfer_requested,
        )

    async def _send_tts_async(
        self,
        call_id: str,
        reply_text: str | None = None,
        template_ids: list[str] | None = None,
        transfer_requested: bool = False,
    ) -> None:
        await self.tts_sender._send_tts_async(
            call_id,
            reply_text=reply_text,
            template_ids=template_ids,
            transfer_requested=transfer_requested,
        )

    async def _wait_for_tts_and_transfer(self, call_id: str, timeout: float = 10.0) -> None:
        await self.playback_manager._wait_for_tts_and_transfer(call_id, timeout=timeout)

    async def _queue_initial_audio_sequence(self, client_id: Optional[str]) -> None:
        await self.sequencer.queue_initial_audio_sequence(client_id)

    async def _flush_tts_queue(self) -> None:
        await self.tts_sender._flush_tts_queue()

    async def _tts_sender_loop(self) -> None:
        await self.tts_sender._tts_sender_loop()

    async def _handle_playback_start(self, call_id: str, audio_file: str) -> None:
        await self.controller.handle_playback_start(call_id, audio_file)

    async def _handle_playback_stop(self, call_id: str) -> None:
        await self.controller.handle_playback_stop(call_id)

    def _load_wav_as_ulaw8k(self, wav_path: Path) -> bytes:
        return self.sequencer._load_wav_as_ulaw8k(wav_path)

    def _generate_silence_ulaw(self, duration_sec: float) -> bytes:
        return self.sequencer._generate_silence_ulaw(duration_sec)

    async def _play_silence_warning(self, call_id: str, warning_interval: float) -> None:
        """
        無音時に流すアナウンス（音源ファイルから再生）

        :param call_id: 通話ID
        :param warning_interval: 警告間隔（5.0, 15.0, 25.0）
        """
        manager = self
        try:
            effective_client_id = (
                manager.client_id or manager.default_client_id or "000"
            )
            audio_file_map = {
                5.0: "000-004.wav",
                15.0: "000-005.wav",
                25.0: "000-006.wav",
            }
            audio_filename = audio_file_map.get(warning_interval)

            if not audio_filename:
                self.logger.warning(
                    "[SILENCE_WARNING] Unknown warning_interval=%s, skipping",
                    warning_interval,
                )
                return

            audio_dir = (
                Path(manager.audio_manager.project_root)
                / "clients"
                / effective_client_id
                / "audio"
            )
            audio_path = audio_dir / audio_filename

            if not audio_path.exists():
                self.logger.warning(
                    "[SILENCE_WARNING] Audio file not found: %s (client_id=%s, interval=%.0fs)",
                    audio_path,
                    effective_client_id,
                    warning_interval,
                )
                return

            self.logger.info(
                "[SILENCE_WARNING] call_id=%s interval=%.0fs audio_file=%s client_id=%s",
                call_id,
                warning_interval,
                audio_path,
                effective_client_id,
            )

            try:
                ulaw_payload = self._load_wav_as_ulaw8k(audio_path)
                chunk_size = 160
                for i in range(0, len(ulaw_payload), chunk_size):
                    manager.tts_queue.append(ulaw_payload[i : i + chunk_size])

                manager.is_speaking_tts = True
                manager._tts_sender_wakeup.set()

                self.logger.debug(
                    "[SILENCE_WARNING] Enqueued %s chunks from %s",
                    len(ulaw_payload) // chunk_size,
                    audio_path,
                )
            except Exception as e:
                self.logger.error(
                    "[SILENCE_WARNING] Failed to load audio file %s: %s",
                    audio_path,
                    e,
                    exc_info=True,
                )
        except Exception as e:
            self.logger.error(
                "Silence warning playback failed for call_id=%s: %s",
                call_id,
                e,
                exc_info=True,
            )

    def _schedule_playback_reset(self, call_id: str, audio_file: str) -> None:
        """Schedule is_playing reset based on wav duration with fallback timeout."""
        try:
            with wave.open(audio_file, "rb") as wf:
                frames = wf.getnframes()
                sample_rate = wf.getframerate()
                duration_sec = frames / float(sample_rate)

            async def _reset_playing_flag_after_duration(call_id: str, duration: float):
                await asyncio.sleep(duration + 0.5)  # バッファ時間を追加
                if hasattr(self.ai_core, "is_playing"):
                    if self.ai_core.is_playing.get(call_id, False):
                        self.ai_core.is_playing[call_id] = False
                        self.logger.info(
                            "[PLAYBACK] is_playing[%s] = False (estimated completion)",
                            call_id,
                        )

            # 【修正1】非同期タスクとして実行（イベントループの存在確認）
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        _reset_playing_flag_after_duration(call_id, duration_sec)
                    )
                else:
                    # ループが実行されていない場合は、スレッドで実行
                    import threading

                    def _reset_in_thread():
                        time.sleep(duration_sec + 0.5)
                        if hasattr(self.ai_core, "is_playing"):
                            if self.ai_core.is_playing.get(call_id, False):
                                self.ai_core.is_playing[call_id] = False
                                self.logger.info(
                                    "[PLAYBACK] is_playing[%s] = False (estimated completion, thread)",
                                    call_id,
                                )

                    threading.Thread(target=_reset_in_thread, daemon=True).start()
            except RuntimeError:
                # イベントループが取得できない場合は、スレッドで実行
                import threading

                def _reset_in_thread():
                    time.sleep(duration_sec + 0.5)
                    if hasattr(self.ai_core, "is_playing"):
                        if self.ai_core.is_playing.get(call_id, False):
                            self.ai_core.is_playing[call_id] = False
                            self.logger.info(
                                "[PLAYBACK] is_playing[%s] = False (estimated completion, thread)",
                                call_id,
                            )

                threading.Thread(target=_reset_in_thread, daemon=True).start()
        except Exception as exc:
            self.logger.debug(
                "[PLAYBACK] Failed to estimate audio duration: %s, using default timeout",
                exc,
            )

            async def _reset_playing_flag_default(call_id: str):
                await asyncio.sleep(10.0)
                if hasattr(self.ai_core, "is_playing"):
                    if self.ai_core.is_playing.get(call_id, False):
                        self.ai_core.is_playing[call_id] = False
                        self.logger.info(
                            "[PLAYBACK] is_playing[%s] = False (default timeout)",
                            call_id,
                        )

            # 【修正1】非同期タスクとして実行（イベントループの存在確認）
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(_reset_playing_flag_default(call_id))
                else:
                    # ループが実行されていない場合は、スレッドで実行
                    import threading

                    def _reset_in_thread():
                        time.sleep(10.0)
                        if hasattr(self.ai_core, "is_playing"):
                            if self.ai_core.is_playing.get(call_id, False):
                                self.ai_core.is_playing[call_id] = False
                                self.logger.info(
                                    "[PLAYBACK] is_playing[%s] = False (default timeout, thread)",
                                    call_id,
                                )

                    threading.Thread(target=_reset_in_thread, daemon=True).start()
            except RuntimeError:
                # イベントループが取得できない場合は、スレッドで実行
                import threading

                def _reset_in_thread():
                    time.sleep(10.0)
                    if hasattr(self.ai_core, "is_playing"):
                        if self.ai_core.is_playing.get(call_id, False):
                            self.ai_core.is_playing[call_id] = False
                            self.logger.info(
                                "[PLAYBACK] is_playing[%s] = False (default timeout, thread)",
                                call_id,
                            )

                threading.Thread(target=_reset_in_thread, daemon=True).start()
