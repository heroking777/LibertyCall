"""Gatewayループ管理"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.core.gateway_lifecycle_manager import GatewayLifecycleManager


class GatewayLoopManager:
    """Gatewayのメインループとシグナルハンドリングを管理"""
    
    def __init__(self, lifecycle_manager: "GatewayLifecycleManager"):
        self.lifecycle_manager = lifecycle_manager
        self.gateway = lifecycle_manager.gateway
        self.logger = logging.getLogger(__name__)
    
    async def run_main_loop(self) -> None:
        """メインループを実行"""
        gateway = self.gateway
        
        # メインループ
        try:
            while gateway.running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            self.logger.info("[MAIN_LOOP] Cancelled, shutting down")
        except Exception as e:
            self.logger.error(f"[MAIN_LOOP] Unexpected error: {e}", exc_info=True)
            raise
    
    def setup_signal_handlers(self) -> None:
        """シグナルハンドラーを設定"""
        loop = asyncio.get_running_loop()
        for sig in (asyncio.signals.SIGINT, asyncio.signals.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)
    
    def _signal_handler(self) -> None:
        """シグナルハンドラー"""
        self.logger.info("[SIGNAL] Received shutdown signal")
        asyncio.create_task(self.gateway.shutdown())
    
    async def shutdown(self, remove_handler_fn=None) -> None:
        """Graceful shutdown for all resources"""
        gateway = self.gateway
        self.logger.info("[SHUTDOWN] Starting graceful shutdown...")
        gateway.running = False
        gateway._complete_console_call()

        if gateway.websocket:
            try:
                await gateway.websocket.close()
                self.logger.debug("[SHUTDOWN] WebSocket closed")
            except Exception as e:
                self.logger.warning(
                    "[SHUTDOWN] Error while closing WebSocket: %s", e
                )

        if gateway.rtp_transport:
            try:
                self.logger.info("[SHUTDOWN] Closing RTP transport...")
                gateway.rtp_transport.close()
                await asyncio.sleep(0.1)
                self.logger.info("[SHUTDOWN] RTP transport closed")
            except Exception as e:
                self.logger.error(
                    "[SHUTDOWN] Error while closing RTP transport: %s", e
                )

        for call_id, timer_task in list(gateway._no_input_timers.items()):
            if timer_task and not timer_task.done():
                try:
                    timer_task.cancel()
                    self.logger.debug(
                        "[SHUTDOWN] Cancelled no_input_timer for call_id=%s",
                        call_id,
                    )
                except Exception as e:
                    self.logger.warning(
                        "[SHUTDOWN] Error cancelling timer for call_id=%s: %s",
                        call_id,
                        e,
                    )
        gateway._no_input_timers.clear()

        if gateway.call_id and remove_handler_fn:
            try:
                remove_handler_fn(gateway.call_id)
                self.logger.info(
                    "[SHUTDOWN] ASR handler removed for call_id=%s",
                    gateway.call_id,
                )
            except Exception as e:
                self.logger.warning(
                    "[SHUTDOWN] Error removing ASR handler: %s", e
                )
