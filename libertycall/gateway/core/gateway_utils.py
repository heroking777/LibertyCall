#!/usr/bin/env python3
"""Gateway utilities for resource and thread management."""
import asyncio
import collections
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from libertycall.gateway.core.gateway_lifecycle_manager import GatewayLifecycleManager
from libertycall.gateway.core.gateway_resource_controller import GatewayResourceController


IGNORE_RTP_IPS = {"160.251.170.253", "127.0.0.1", "::1"}


class GatewayUtils:
    def __init__(self, gateway: "RealtimeGateway", rtp_builder_cls, rtp_protocol_cls):
        self.gateway = gateway
        self.logger = gateway.logger
        self.rtp_builder_cls = rtp_builder_cls
        self.rtp_protocol_cls = rtp_protocol_cls
        self.lifecycle = GatewayLifecycleManager(self)
        self.resources = GatewayResourceController(self)

    def init_state(self, console_bridge, audio_manager) -> None:
        self.lifecycle.init_state(console_bridge, audio_manager)

    async def start(self):
        await self.lifecycle.start()

    async def shutdown(self, remove_handler_fn=None) -> None:
        await self.lifecycle.shutdown(remove_handler_fn)

    def complete_console_call(self) -> None:
        gateway = self.gateway
        if not gateway.console_bridge.enabled or not gateway.call_id or gateway.call_completed:
            return
        call_id_to_complete = gateway.call_id
        try:
            gateway.console_bridge.complete_call(
                call_id_to_complete, ended_at=datetime.utcnow()
            )
            if gateway.streaming_enabled:
                gateway.ai_core.reset_call(call_id_to_complete)
            if hasattr(gateway.ai_core, "on_call_end"):
                gateway.ai_core.on_call_end(
                    call_id_to_complete, source="_complete_console_call"
                )
            if hasattr(gateway.ai_core, "cleanup_asr_instance"):
                gateway.ai_core.cleanup_asr_instance(call_id_to_complete)
            gateway.call_completed = True
            gateway.call_id = None
            gateway.recent_dialogue.clear()
            gateway.transfer_notified = False
            gateway.last_audio_level_sent = 0.0
            gateway.last_audio_level_time = 0.0
        except Exception as e:
            self.logger.error(
                "[COMPLETE_CALL_ERR] Error during _complete_console_call for call_id=%s: %s",
                call_id_to_complete,
                e,
                exc_info=True,
            )
        finally:
            self.logger.warning(
                "[FINALLY_BLOCK_ENTRY] Entered finally block for call_id=%s",
                call_id_to_complete,
            )
            if call_id_to_complete:
                complete_time = time.time()
                self.logger.warning(
                    "[FINALLY_ACTIVE_CALLS] Before removal: call_id=%s in _active_calls=%s",
                    call_id_to_complete,
                    call_id_to_complete in gateway._active_calls
                    if hasattr(gateway, "_active_calls")
                    else False,
                )
                if (
                    hasattr(gateway, "_active_calls")
                    and call_id_to_complete in gateway._active_calls
                ):
                    gateway._active_calls.remove(call_id_to_complete)
                    self.logger.warning(
                        "[COMPLETE_CALL_DONE] Removed %s from active_calls (finally block) at %.3f",
                        call_id_to_complete,
                        complete_time,
                    )
                self.logger.warning(
                    "[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id=%s in _active_calls=%s",
                    call_id_to_complete,
                    call_id_to_complete in gateway._active_calls
                    if hasattr(gateway, "_active_calls")
                    else False,
                )

                if call_id_to_complete in gateway._recovery_counts:
                    del gateway._recovery_counts[call_id_to_complete]
                if call_id_to_complete in gateway._initial_sequence_played:
                    gateway._initial_sequence_played.discard(call_id_to_complete)
                if call_id_to_complete in gateway._last_processed_sequence:
                    del gateway._last_processed_sequence[call_id_to_complete]
                gateway._last_voice_time.pop(call_id_to_complete, None)
                gateway._last_silence_time.pop(call_id_to_complete, None)
                gateway._last_tts_end_time.pop(call_id_to_complete, None)
                gateway._last_user_input_time.pop(call_id_to_complete, None)
                gateway._silence_warning_sent.pop(call_id_to_complete, None)
                if hasattr(gateway, "_initial_tts_sent"):
                    gateway._initial_tts_sent.discard(call_id_to_complete)
                self.logger.debug(
                    "[CALL_CLEANUP] Cleared state for call_id=%s",
                    call_id_to_complete,
                )
        gateway.user_turn_index = 0
        gateway.call_start_time = None
        gateway._reset_call_state()

    def reset_call_state(self) -> None:
        gateway = self.gateway
        was_playing = gateway.initial_sequence_playing
        gateway.initial_sequence_played = False
        gateway.initial_sequence_playing = False
        gateway.initial_sequence_completed = False
        gateway.initial_sequence_completed_time = None
        if gateway._asr_enable_timer:
            try:
                gateway._asr_enable_timer.cancel()
            except Exception:
                pass
            gateway._asr_enable_timer = None
        if was_playing:
            self.logger.info(
                "[INITIAL_SEQUENCE] OFF: call state reset (initial_sequence_playing=False)"
            )
        gateway.tts_queue.clear()
        gateway.is_speaking_tts = False
        gateway.audio_buffer = bytearray()
        gateway.current_segment_start = None
        gateway.is_user_speaking = False
        gateway.last_voice_time = time.time()
        gateway.rtp_peer = None
        gateway._rtp_src_addr = None
        gateway.rtp_packet_count = 0
        gateway.last_rtp_packet_time = 0.0
        gateway._last_tts_text = None

        gateway._stream_chunk_counter = 0
        gateway._last_feed_time = time.time()

        old_call_id = gateway.call_id
        gateway.call_id = None
        gateway.call_start_time = None
        gateway.user_turn_index = 0
        gateway.call_completed = False
        gateway.transfer_notified = False
        gateway.recent_dialogue.clear()

        if old_call_id:
            gateway._last_user_input_time.pop(old_call_id, None)
            gateway._last_tts_end_time.pop(old_call_id, None)
            gateway._no_input_elapsed.pop(old_call_id, None)
            if old_call_id in gateway._no_input_timers:
                timer_task = gateway._no_input_timers.pop(old_call_id)
                if timer_task and not timer_task.done():
                    timer_task.cancel()

        if hasattr(gateway.ai_core, "set_call_id"):
            gateway.ai_core.set_call_id(None)
        if hasattr(gateway.ai_core, "call_id"):
            gateway.ai_core.call_id = None
        if hasattr(gateway.ai_core, "log_session_id"):
            gateway.ai_core.log_session_id = None

        if old_call_id:
            self.logger.info(
                "[RESET_CALL_STATE] call_id reset: %s -> None", old_call_id
            )

        gateway._stop_recording()

    def _free_port(self, port: int):
        self.resources._free_port(port)

    def _recover_esl_connection(self, max_retries: int = 3) -> bool:
        return self.lifecycle._recover_esl_connection(max_retries=max_retries)

    def _start_esl_event_listener(self) -> None:
        self.lifecycle._start_esl_event_listener()

    def _update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
        return self.resources._update_uuid_mapping_directly(call_id)

    def _find_rtp_info_by_port(self, rtp_port: int) -> Optional[str]:
        return self.resources._find_rtp_info_by_port(rtp_port)

    def _get_effective_call_id(
        self, addr: Optional[Tuple[str, int]] = None
    ) -> Optional[str]:
        """
        RTP受信時に有効なcall_idを決定する。

        :param addr: RTP送信元のアドレス (host, port)。Noneの場合は既存のロジックを使用
        :return: 有効なcall_id、見つからない場合はNone
        """
        gateway = self.gateway
        # アドレスが指定されている場合は、アドレス紐づけを優先
        if addr and hasattr(gateway, "_call_addr_map") and addr in gateway._call_addr_map:
            return gateway._call_addr_map[addr]

        # すでにアクティブ通話が1件のみの場合はそれを使う
        if hasattr(gateway, "_active_calls") and len(gateway._active_calls) == 1:
            return next(iter(gateway._active_calls))

        # アクティブな通話がある場合は最後に開始された通話を使用
        if hasattr(gateway, "_active_calls") and gateway._active_calls:
            active = list(gateway._active_calls)
            if active:
                return active[-1]  # 最後に開始された通話を使用

        # 既存のロジック（call_idが未設定の場合は正式なcall_idを生成）
        if not gateway.call_id:
            # call_idが未設定の場合は正式なcall_idを生成
            if gateway.client_id:
                gateway.call_id = gateway.console_bridge.issue_call_id(gateway.client_id)
                self.logger.debug("Generated call_id: %s", gateway.call_id)
                # AICoreにcall_idを設定
                if gateway.call_id:
                    gateway.ai_core.set_call_id(gateway.call_id)
            else:
                # client_idが未設定の場合はデフォルト値を使用（警告を出さない）
                effective_client_id = gateway.default_client_id or "000"
                gateway.call_id = gateway.console_bridge.issue_call_id(
                    effective_client_id
                )
                self.logger.debug(
                    "Generated call_id: %s using default client_id=%s",
                    gateway.call_id,
                    effective_client_id,
                )
                # AICoreにcall_idを設定
                if gateway.call_id:
                    gateway.ai_core.set_call_id(gateway.call_id)
                    # client_idも設定
                    gateway.client_id = effective_client_id
                    self.logger.debug(
                        "Set client_id to default: %s", effective_client_id
                    )

        return gateway.call_id

    def _maybe_send_audio_level(self, rms: int) -> None:
        """RMS値を正規化して、一定間隔で音量レベルを管理画面に送信。"""
        gateway = self.gateway
        if not gateway.console_bridge.enabled or not gateway.call_id:
            return

        now = time.time()
        # RMSを0.0〜1.0に正規化
        normalized_level = min(1.0, rms / gateway.RMS_MAX)

        # 送信間隔チェック
        time_since_last = now - gateway.last_audio_level_time
        if time_since_last < gateway.AUDIO_LEVEL_INTERVAL:
            return

        # レベル変化が小さい場合は送らない（スパム防止）
        level_diff = abs(normalized_level - gateway.last_audio_level_sent)
        if level_diff < gateway.AUDIO_LEVEL_THRESHOLD and normalized_level < 0.1:
            return

        # 送信
        gateway.console_bridge.send_audio_level(
            gateway.call_id,
            normalized_level,
            direction="user",
            client_id=gateway.client_id,
        )
        gateway.last_audio_level_sent = normalized_level
        gateway.last_audio_level_time = now
