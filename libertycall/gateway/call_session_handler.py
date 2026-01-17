#!/usr/bin/env python3
"""Call session handling for FreeSWITCH/Asterisk events."""
import asyncio
import time
from typing import Optional

from libertycall.gateway.call_lifecycle_handler import CallLifecycleHandler
from libertycall.gateway.call_uuid_manager import CallUUIDManager


class GatewayCallSessionHandler:
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        self.logger = gateway.logger
        self.lifecycle = CallLifecycleHandler(self)
        self.uuid_manager = CallUUIDManager(self)

    async def _handle_init_from_asterisk(self, data: dict):
        await self.lifecycle.handle_init_from_asterisk(data)

    def _handle_transfer(self, call_id: str) -> None:
        self.lifecycle.handle_transfer(call_id)

    def _update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
        return self.uuid_manager.update_uuid_mapping_directly(call_id)

    def update_uuid_mapping_for_call(self, call_id: str) -> Optional[str]:
        return self.uuid_manager.update_uuid_mapping_for_call(call_id)

    def _handle_hangup(self, call_id: str) -> None:
        self.lifecycle.handle_hangup(call_id)

    async def _handle_no_input_timeout(self, call_id: str):
        """
        無音タイムアウトを処理: NOT_HEARD intentをai_coreに渡す

        :param call_id: 通話ID
        """
        gateway = self.gateway
        try:
            # 【デバッグ】無音タイムアウト発火
            state = gateway.ai_core._get_session_state(call_id)
            streak_before = state.no_input_streak
            streak = min(streak_before + 1, gateway.NO_INPUT_STREAK_LIMIT)

            # 明示的なデバッグログを追加
            self.logger.debug(
                f"[NO_INPUT] Triggered for call_id={call_id}, streak={streak}"
            )
            self.logger.info(
                f"[NO_INPUT] Triggered for call_id={call_id}, streak={streak}"
            )

            # 発信者番号を取得（ログ出力用）
            caller_number = getattr(gateway.ai_core, "caller_number", None) or "未設定"
            self.logger.debug(
                f"[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}"
            )
            self.logger.info(
                f"[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}"
            )

            # ai_coreの状態を取得
            no_input_streak = streak
            state.no_input_streak = no_input_streak
            # 無音経過時間を累積
            elapsed = gateway._no_input_elapsed.get(call_id, 0.0) + gateway.NO_INPUT_TIMEOUT
            gateway._no_input_elapsed[call_id] = elapsed

            self.logger.debug(
                "[NO_INPUT] call_id=%s caller=%s streak=%s elapsed=%.1fs (incrementing)",
                call_id,
                caller_number,
                no_input_streak,
                elapsed,
            )
            self.logger.info(
                "[NO_INPUT] call_id=%s caller=%s streak=%s elapsed=%.1fs (incrementing)",
                call_id,
                caller_number,
                no_input_streak,
                elapsed,
            )

            # NOT_HEARD intentとして処理（空のテキストで呼び出す）
            # ai_core側でno_input_streakに基づいてテンプレートを選択する
            reply_text = gateway.ai_core.on_transcript(call_id, "", is_final=True)

            if reply_text:
                # TTS送信（テンプレートIDはai_core側で決定される）
                template_ids = (
                    state.last_ai_templates if hasattr(state, "last_ai_templates") else []
                )
                gateway._send_tts(call_id, reply_text, template_ids, False)

                # テンプレート112の場合は自動切断を予約（ai_core側で処理される）
                if "112" in template_ids:
                    self.logger.info(
                        f"[NO_INPUT] call_id={call_id} template=112 detected, auto_hangup will be scheduled"
                    )

            # 最大無音時間を超えた場合は強制切断を実行（管理画面でも把握しやすいよう詳細ログ）
            if gateway._no_input_elapsed.get(call_id, 0.0) >= gateway.MAX_NO_INPUT_TIME:
                elapsed_total = gateway._no_input_elapsed.get(call_id, 0.0)
                self.logger.debug(
                    "[NO_INPUT] call_id=%s caller=%s exceeded MAX_NO_INPUT_TIME=%ss "
                    "(streak=%s, elapsed=%.1fs) -> FORCE_HANGUP",
                    call_id,
                    caller_number,
                    gateway.MAX_NO_INPUT_TIME,
                    no_input_streak,
                    elapsed_total,
                )
                self.logger.warning(
                    "[NO_INPUT] call_id=%s caller=%s exceeded MAX_NO_INPUT_TIME=%ss "
                    "(streak=%s, elapsed=%.1fs) -> FORCE_HANGUP",
                    call_id,
                    caller_number,
                    gateway.MAX_NO_INPUT_TIME,
                    no_input_streak,
                    elapsed_total,
                )
                # 直前の状態を詳細ログに出力（原因追跡用）
                self.logger.debug(
                    "[FORCE_HANGUP] Preparing disconnect: call_id=%s caller=%s "
                    "elapsed=%.1fs streak=%s max_timeout=%ss",
                    call_id,
                    caller_number,
                    elapsed_total,
                    no_input_streak,
                    gateway.MAX_NO_INPUT_TIME,
                )
                self.logger.warning(
                    "[FORCE_HANGUP] Preparing disconnect: call_id=%s caller=%s "
                    "elapsed=%.1fs streak=%s max_timeout=%ss",
                    call_id,
                    caller_number,
                    elapsed_total,
                    no_input_streak,
                    gateway.MAX_NO_INPUT_TIME,
                )
                self.logger.debug(
                    "[FORCE_HANGUP] Attempting to disconnect call_id=%s after %.1fs of silence "
                    "(streak=%s, timeout=%ss)",
                    call_id,
                    elapsed_total,
                    no_input_streak,
                    gateway.MAX_NO_INPUT_TIME,
                )
                self.logger.info(
                    "[FORCE_HANGUP] Attempting to disconnect call_id=%s after %.1fs of silence "
                    "(streak=%s, timeout=%ss)",
                    call_id,
                    elapsed_total,
                    no_input_streak,
                    gateway.MAX_NO_INPUT_TIME,
                )
                # 1分無音継続時は強制切断をスケジュール（確実に実行）
                try:
                    if hasattr(gateway.ai_core, "_schedule_auto_hangup"):
                        gateway.ai_core._schedule_auto_hangup(call_id, delay_sec=1.0)
                        self.logger.info(
                            "[NO_INPUT] FORCE_HANGUP_SCHEDULED: call_id=%s caller=%s "
                            "elapsed=%.1fs delay=1.0s",
                            call_id,
                            caller_number,
                            elapsed_total,
                        )
                    elif gateway.ai_core.hangup_callback:
                        # _schedule_auto_hangupが存在しない場合は直接コールバックを呼び出す
                        self.logger.info(
                            "[NO_INPUT] FORCE_HANGUP_DIRECT: call_id=%s caller=%s "
                            "elapsed=%.1fs (no _schedule_auto_hangup method)",
                            call_id,
                            caller_number,
                            elapsed_total,
                        )
                        gateway.ai_core.hangup_callback(call_id)
                    else:
                        self.logger.error(
                            "[NO_INPUT] FORCE_HANGUP_FAILED: call_id=%s caller=%s hangup_callback not set",
                            call_id,
                            caller_number,
                        )
                except Exception as e:
                    self.logger.exception(
                        "[NO_INPUT] FORCE_HANGUP_ERROR: call_id=%s caller=%s error=%r",
                        call_id,
                        caller_number,
                        e,
                    )
                # 強制切断後は処理を終了
                return

        except Exception as e:
            self.logger.exception(
                f"[NO_INPUT] Error handling timeout for call_id={call_id}: {e}"
            )
