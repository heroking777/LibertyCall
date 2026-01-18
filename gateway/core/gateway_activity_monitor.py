"""Gateway activity monitor (recording, timers, silence warnings)."""
from __future__ import annotations

import asyncio
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from ..realtime_gateway import RealtimeGateway


class GatewayActivityMonitor:
    def __init__(self, gateway: "RealtimeGateway") -> None:
        self.gateway = gateway
        self.logger = gateway.logger

    def _start_recording(self) -> None:
        """録音を開始する"""
        gateway = self.gateway
        if not gateway.recording_enabled or gateway.recording_file is not None:
            return

        try:
            recordings_dir = Path("/opt/libertycall/recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)

            call_id_str = gateway.call_id or "unknown"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"call_{call_id_str}_{timestamp}.wav"
            gateway.recording_path = recordings_dir / filename

            gateway.recording_file = wave.open(str(gateway.recording_path), "wb")
            gateway.recording_file.setnchannels(1)
            gateway.recording_file.setsampwidth(2)
            gateway.recording_file.setframerate(8000)

            self.logger.info(
                "録音開始: call_id=%s path=%s", call_id_str, gateway.recording_path
            )
        except Exception as e:
            self.logger.error("録音開始エラー: %s", e, exc_info=True)
            gateway.recording_file = None
            gateway.recording_path = None

    def _stop_recording(self) -> None:
        """録音を停止する"""
        gateway = self.gateway
        if gateway.recording_file is not None:
            try:
                gateway.recording_file.close()
                self.logger.info("録音停止: path=%s", gateway.recording_path)
            except Exception as e:
                self.logger.error("録音停止エラー: %s", e, exc_info=True)
            finally:
                gateway.recording_file = None
                gateway.recording_path = None

    async def _start_no_input_timer(self, call_id: str) -> None:
        """無音検知タイマーを起動する（async対応版、既存タスクがあればキャンセルして再起動）"""
        gateway = self.gateway
        try:
            existing = gateway._no_input_timers.pop(call_id, None)
            if existing and not existing.done():
                existing.cancel()
                self.logger.debug(
                    "[DEBUG_INIT] Cancelled existing no_input_timer for call_id=%s",
                    call_id,
                )

            now = time.monotonic()
            gateway._last_user_input_time[call_id] = now
            gateway._last_tts_end_time[call_id] = now
            gateway._no_input_elapsed[call_id] = 0.0

            async def _timer():
                try:
                    await asyncio.sleep(gateway.NO_INPUT_TIMEOUT)
                    if not gateway.running:
                        return
                    await gateway._handle_no_input_timeout(call_id)
                except asyncio.CancelledError:
                    self.logger.debug(
                        "[DEBUG_INIT] no_input_timer cancelled for call_id=%s", call_id
                    )
                finally:
                    gateway._no_input_timers.pop(call_id, None)

            task = asyncio.create_task(_timer())
            gateway._no_input_timers[call_id] = task
            self.logger.debug(
                "[DEBUG_INIT] no_input_timer started for call_id=%s (timeout=%ss, task=%s, done=%s, cancelled=%s)",
                call_id,
                gateway.NO_INPUT_TIMEOUT,
                task,
                task.done(),
                task.cancelled(),
            )
            self.logger.info(
                "[DEBUG_INIT] no_input_timer started for call_id=%s (timeout=%ss, task_done=%s, task_cancelled=%s)",
                call_id,
                gateway.NO_INPUT_TIMEOUT,
                task.done(),
                task.cancelled(),
            )
        except Exception as e:
            self.logger.exception(
                "[NO_INPUT] Failed to start no_input_timer for call_id=%s: %s",
                call_id,
                e,
            )

    async def _wait_for_no_input_reset(self, call_id: str) -> None:
        """無音タイムアウト処理後、次のタイムアウトまで待機する"""
        gateway = self.gateway
        await asyncio.sleep(gateway.NO_INPUT_TIMEOUT + 1.0)
        if call_id in gateway._no_input_timers:
            del gateway._no_input_timers[call_id]
