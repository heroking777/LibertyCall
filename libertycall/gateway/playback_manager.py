"""Playback/TTS manager extracted from realtime_gateway."""

from __future__ import annotations

import asyncio
import time
from typing import Optional, TYPE_CHECKING

import wave

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
