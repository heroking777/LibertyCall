"""Playback/TTS manager extracted from realtime_gateway."""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import audioop
import wave

from libertycall.gateway.tts_sender import TTSSender
from libertycall.gateway.playback_controller import PlaybackController

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


_CURRENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CURRENT_DIR.parent.parent


class GatewayPlaybackManager:
    """Move playback/TTS logic out of RealtimeGateway."""

    def __init__(self, gateway: "RealtimeGateway") -> None:
        super().__setattr__("gateway", gateway)
        super().__setattr__("logger", gateway.logger)
        super().__setattr__("tts_sender", TTSSender(self))
        super().__setattr__("controller", PlaybackController(self))

    def __getattr__(self, name: str):
        return getattr(self.gateway, name)

    def __setattr__(self, name: str, value) -> None:
        if name in {"gateway", "logger"}:
            super().__setattr__(name, value)
        else:
            setattr(self.gateway, name, value)

    def _handle_playback(self, call_id: str, audio_file: str) -> None:
        """
        FreeSWITCHに音声再生リクエストを送信（ESL使用、自動リカバリ対応）

        :param call_id: 通話UUID
        :param audio_file: 音声ファイルのパス
        """
        # 【修正】call_idが_active_callsに存在しない場合は自動追加
        if not hasattr(self, "_active_calls"):
            self._active_calls = set()
        elif not self._active_calls:
            self._active_calls = set()

        if call_id not in self._active_calls:
            # call_uuid_mapでUUID→call_id変換を試す
            call_id_found = False
            if hasattr(self, "call_uuid_map"):
                for mapped_call_id, mapped_uuid in self.call_uuid_map.items():
                    if mapped_uuid == call_id and mapped_call_id in self._active_calls:
                        call_id_found = True
                        self.logger.info(
                            f"[PLAYBACK] Found call_id via UUID mapping: {call_id} -> {mapped_call_id}"
                        )
                        break

            if not call_id_found:
                # 自動追加（再生リクエストがある = 通話がアクティブ）
                self.logger.info(
                    f"[PLAYBACK] Auto-adding call_id={call_id} to _active_calls "
                    f"(playback request received, current active_calls: {self._active_calls})"
                )
                self._active_calls.add(call_id)

        try:
            # ESL接続が切れている場合は自動リカバリを試みる
            if not self.esl_connection or not self.esl_connection.connected():
                self.logger.warning(
                    f"[PLAYBACK] ESL not available, attempting recovery: call_id={call_id} file={audio_file}"
                )
                self._recover_esl_connection()

                # 再接続に失敗した場合はスキップ
                if not self.esl_connection or not self.esl_connection.connected():
                    self.logger.error(
                        f"[PLAYBACK] ESL recovery failed, skipping playback: call_id={call_id} file={audio_file}"
                    )
                    return

            # 再生開始: is_playing[uuid] = True を設定
            if hasattr(self.ai_core, "is_playing"):
                self.ai_core.is_playing[call_id] = True
                self.logger.info(f"[PLAYBACK] is_playing[{call_id}] = True")

            # 【修正1】再生前のUUID先読み更新（Pre-emptive Update）
            # call_idからFreeSWITCH UUIDに変換（マッピングが存在する場合）
            freeswitch_uuid = self.call_uuid_map.get(call_id, call_id)

            # UUIDの有効性を事前確認（先読み更新）
            # 【修正1】より積極的にUUID更新を実行（常にUUID更新を試行）
            uuid_needs_update = True  # 常にUUID更新を試行

            if uuid_needs_update:
                self.logger.info(
                    f"[PLAYBACK] Pre-emptive UUID update: call_id={call_id} current_uuid={freeswitch_uuid}"
                )
                # UUIDを先読み更新
                new_uuid = None
                if hasattr(self, "fs_rtp_monitor") and self.fs_rtp_monitor:
                    new_uuid = self.fs_rtp_monitor.update_uuid_mapping_for_call(call_id)

                if not new_uuid:
                    self.logger.info(
                        f"[PLAYBACK] Pre-emptive UUID lookup: executing direct lookup for call_id={call_id}"
                    )
                    new_uuid = self._update_uuid_mapping_directly(call_id)

                if new_uuid:
                    freeswitch_uuid = new_uuid
                    self.logger.info(
                        f"[PLAYBACK] Pre-emptive UUID update successful: call_id={call_id} -> uuid={freeswitch_uuid}"
                    )
                else:
                    self.logger.warning(
                        f"[PLAYBACK] Pre-emptive UUID update failed, using current UUID: call_id={call_id} uuid={freeswitch_uuid}"
                    )
            else:
                self.logger.debug(
                    f"[PLAYBACK] Using mapped UUID: call_id={call_id} -> uuid={freeswitch_uuid}"
                )

            # 【修正3】110連打防止: 再生リクエスト送信時にlast_activityを更新（成否に関わらず）
            # 再生リクエスト送信直前で更新することで、リクエストの成否に関わらずタイマーをリセット
            if hasattr(self.ai_core, "last_activity"):
                self.ai_core.last_activity[call_id] = time.time()
                self.logger.info(
                    f"[PLAYBACK] Updated last_activity on request: call_id={call_id} (preventing timeout loop)"
                )

            # ESLを使ってuuid_playbackを実行（非同期実行で応答速度を最適化）
            result = self.esl_connection.execute(
                "playback", audio_file, uuid=freeswitch_uuid, force_async=True
            )

            playback_success = False
            invalid_session = False
            # 【修正3】再生成功フラグをselfに保存（finallyブロックでアクセス可能にする）
            self._last_playback_success = False
            if result:
                reply_text = (
                    result.getHeader("Reply-Text") if hasattr(result, "getHeader") else None
                )
                if reply_text and "+OK" in reply_text:
                    playback_success = True
                    self._last_playback_success = True
                    self.logger.info(
                        f"[PLAYBACK] Playback started: call_id={call_id} file={audio_file} uuid={freeswitch_uuid}"
                    )
                else:
                    # invalid session idエラーを検知
                    if reply_text and "invalid session id" in reply_text.lower():
                        invalid_session = True
                        # 【修正3】invalid session id検出時は最大3回までリトライ
                        if not hasattr(self, "_playback_retry_count"):
                            self._playback_retry_count = {}
                        retry_count = self._playback_retry_count.get(call_id, 0)
                        if retry_count < 3:
                            self.logger.warning(
                                f"[PLAYBACK] Invalid session id detected: call_id={call_id} uuid={freeswitch_uuid} reply={reply_text} (retry {retry_count + 1}/3)"
                            )
                        else:
                            self.logger.error(
                                f"[PLAYBACK] Invalid session id detected: call_id={call_id} uuid={freeswitch_uuid} reply={reply_text} (max retries exceeded)"
                            )
                    else:
                        self.logger.warning(
                            f"[PLAYBACK] Playback command may have failed: call_id={call_id} reply={reply_text}"
                        )
            else:
                self.logger.warning(f"[PLAYBACK] No response from ESL: call_id={call_id}")

            # 【修正3】invalid session idエラー時、UUIDマッピングを再取得してリトライ（最大3回まで）
            if invalid_session:
                # リトライカウントを初期化（まだ存在しない場合）
                if not hasattr(self, "_playback_retry_count"):
                    self._playback_retry_count = {}
                retry_count = self._playback_retry_count.get(call_id, 0)
                max_retries = 3

                if retry_count < max_retries:
                    # リトライカウントを増加
                    self._playback_retry_count[call_id] = retry_count + 1
                    self.logger.info(
                        f"[PLAYBACK] Attempting UUID remapping for call_id={call_id} (retry {retry_count + 1}/{max_retries})"
                    )
                # 【修正1】UUIDマッピングを再取得（fs_rtp_monitorを使用、見つからない場合はRealtimeGateway自身が実行）
                new_uuid = None
                if hasattr(self, "fs_rtp_monitor") and self.fs_rtp_monitor:
                    new_uuid = self.fs_rtp_monitor.update_uuid_mapping_for_call(call_id)

                # 【修正2】Monitorが見つからない場合でも、RealtimeGateway自身がshow channelsを実行
                if not new_uuid:
                    self.logger.info(
                        f"[PLAYBACK] fs_rtp_monitor not available, executing UUID lookup directly: call_id={call_id}"
                    )
                    new_uuid = self._update_uuid_mapping_directly(call_id)
                    if new_uuid:
                        self.logger.info(
                            f"[PLAYBACK] UUID remapped: call_id={call_id} -> new_uuid={new_uuid} (remapping successful)"
                        )
                        # 再取得したUUIDでリトライ
                        freeswitch_uuid = new_uuid
                        retry_result = self.esl_connection.execute(
                            "playback", audio_file, uuid=freeswitch_uuid, force_async=True
                        )
                        if retry_result:
                            retry_reply = (
                                retry_result.getHeader("Reply-Text")
                                if hasattr(retry_result, "getHeader")
                                else None
                            )
                            if retry_reply and "+OK" in retry_reply:
                                playback_success = True
                                self._last_playback_success = True
                                # リトライ成功時はカウントをリセット
                                self._playback_retry_count[call_id] = 0
                                self.logger.info(
                                    f"[PLAYBACK] Playback started (after remap): call_id={call_id} file={audio_file} uuid={freeswitch_uuid}"
                                )
                            else:
                                # リトライも失敗した場合、フォールバックを試みる（1回のみ）
                                if retry_reply and "invalid session id" in retry_reply.lower():
                                    self.logger.warning(
                                        f"[PLAYBACK] Retry also failed with invalid session id: call_id={call_id} reply={retry_reply}"
                                    )
                                    # フォールバック: call_idを直接使用（これが最後の試み）
                                    self.logger.warning(
                                        f"[PLAYBACK] Attempting final fallback: using call_id as UUID: call_id={call_id}"
                                    )
                                    freeswitch_uuid = call_id
                                    fallback_result = self.esl_connection.execute(
                                        "playback", audio_file, uuid=freeswitch_uuid, force_async=True
                                    )
                                    if fallback_result:
                                        fallback_reply = (
                                            fallback_result.getHeader("Reply-Text")
                                            if hasattr(fallback_result, "getHeader")
                                            else None
                                        )
                                        if fallback_reply and "+OK" in fallback_reply:
                                            playback_success = True
                                            self._last_playback_success = True
                                            # リトライ成功時はカウントをリセット
                                            self._playback_retry_count[call_id] = 0
                                            self.logger.info(
                                                f"[PLAYBACK] Playback started (final fallback): call_id={call_id} file={audio_file} uuid={freeswitch_uuid}"
                                            )
                                        else:
                                            self.logger.error(
                                                f"[PLAYBACK] Final fallback failed: call_id={call_id} reply={fallback_reply} (no more retries)"
                                            )
                                    else:
                                        self.logger.error(
                                            "[PLAYBACK] Final fallback failed: no response from ESL (no more retries)"
                                        )
                                else:
                                    self.logger.warning(
                                        f"[PLAYBACK] Retry failed: call_id={call_id} reply={retry_reply}"
                                    )
                                    # リトライカウントをリセット（最大リトライ回数に達した場合）
                                    self._playback_retry_count[call_id] = 0
                                    self.logger.error(
                                        f"[PLAYBACK] Retry limit reached (max_retries={max_retries}), aborting playback: call_id={call_id}"
                                    )
                        else:
                            self.logger.warning("[PLAYBACK] Retry failed: no response from ESL")
                            # リトライカウントをリセット（最大リトライ回数に達した場合）
                            self._playback_retry_count[call_id] = 0
                            self.logger.error(
                                f"[PLAYBACK] Retry limit reached (max_retries={max_retries}), aborting playback: call_id={call_id}"
                            )
                else:
                    # 最大リトライ回数に達した場合
                    self.logger.error(
                        f"[PLAYBACK] Max retries exceeded for call_id={call_id} (retry_count={retry_count}, max_retries={max_retries})"
                    )
                    # リトライカウントをリセット
                    self._playback_retry_count[call_id] = 0

                # UUID再取得に失敗した場合の処理（retry_count < max_retries の外側で処理）
                if not new_uuid and retry_count < max_retries:
                    # UUID再取得に失敗した場合、call_idを直接使用（フォールバック、1回のみ）
                    self.logger.warning(
                        f"[PLAYBACK] UUID remapping failed, using call_id as UUID (fallback): call_id={call_id}"
                    )
                    freeswitch_uuid = call_id
                    fallback_result = self.esl_connection.execute(
                        "playback", audio_file, uuid=freeswitch_uuid, force_async=True
                    )
                    if fallback_result:
                        fallback_reply = (
                            fallback_result.getHeader("Reply-Text")
                            if hasattr(fallback_result, "getHeader")
                            else None
                        )
                        if fallback_reply and "+OK" in fallback_reply:
                            playback_success = True
                            self._last_playback_success = True
                            # リトライ成功時はカウントをリセット
                            self._playback_retry_count[call_id] = 0
                            self.logger.info(
                                f"[PLAYBACK] Playback started (fallback): call_id={call_id} file={audio_file} uuid={freeswitch_uuid}"
                            )
                        else:
                            self.logger.error(
                                f"[PLAYBACK] Fallback also failed: call_id={call_id} reply={fallback_reply} (no more retries)"
                            )
                    else:
                        self.logger.error(
                            "[PLAYBACK] Fallback failed: no response from ESL (no more retries)"
                        )
                else:
                    # UUID再取得に失敗した場合、call_idを直接使用（フォールバック、1回のみ）
                    self.logger.warning(
                        f"[PLAYBACK] UUID remapping failed (both monitor and direct lookup), using call_id as UUID (fallback): call_id={call_id}"
                    )
                    freeswitch_uuid = call_id
                    fallback_result = self.esl_connection.execute(
                        "playback", audio_file, uuid=freeswitch_uuid, force_async=True
                    )
                    if fallback_result:
                        fallback_reply = (
                            fallback_result.getHeader("Reply-Text")
                            if hasattr(fallback_result, "getHeader")
                            else None
                        )
                        if fallback_reply and "+OK" in fallback_reply:
                            playback_success = True
                            self._last_playback_success = True
                            self.logger.info(
                                f"[PLAYBACK] Playback started (fallback): call_id={call_id} file={audio_file} uuid={freeswitch_uuid}"
                            )
                        else:
                            self.logger.error(
                                f"[PLAYBACK] Fallback also failed: call_id={call_id} reply={fallback_reply} (no more retries)"
                            )
                    else:
                        self.logger.error(
                            "[PLAYBACK] Fallback failed: no response from ESL (no more retries)"
                        )

            # 簡易実装: 音声ファイルの長さを推定して、その時間後にis_playingをFalseにする
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
                                f"[PLAYBACK] is_playing[{call_id}] = False (estimated completion)"
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
                                        f"[PLAYBACK] is_playing[{call_id}] = False (estimated completion, thread)"
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
                                    f"[PLAYBACK] is_playing[{call_id}] = False (estimated completion, thread)"
                                )

                    threading.Thread(target=_reset_in_thread, daemon=True).start()
            except Exception as e:
                self.logger.debug(
                    f"[PLAYBACK] Failed to estimate audio duration: {e}, using default timeout"
                )
                # エラー時はデフォルトタイムアウト（10秒）を使用
                async def _reset_playing_flag_default(call_id: str):
                    await asyncio.sleep(10.0)
                    if hasattr(self.ai_core, "is_playing"):
                        if self.ai_core.is_playing.get(call_id, False):
                            self.ai_core.is_playing[call_id] = False
                            self.logger.info(
                                f"[PLAYBACK] is_playing[{call_id}] = False (default timeout)"
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
                                        f"[PLAYBACK] is_playing[{call_id}] = False (default timeout, thread)"
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
                                    f"[PLAYBACK] is_playing[{call_id}] = False (default timeout, thread)"
                                )

                    threading.Thread(target=_reset_in_thread, daemon=True).start()

        except Exception as e:
            self.logger.exception(f"[PLAYBACK] Failed to send playback request: {e}")
            # 【修正3】エラー時はis_playingをFalseにする（次の発話認識をブロックしない）
            self._last_playback_success = False
            if hasattr(self.ai_core, "is_playing"):
                self.ai_core.is_playing[call_id] = False
                self.logger.info(
                    f"[PLAYBACK] Set is_playing[{call_id}] = False (due to error)"
                )
        finally:
            # 【修正3】再生リクエストの成否に関わらず、再生失敗時はis_playingをFalseに戻す
            # 再生成功時はis_playingをTrueのままにして、再生完了イベントでFalseにする
            # 再生失敗時（playback_successがFalse）の場合のみFalseに設定
            if hasattr(self, "_last_playback_success") and not self._last_playback_success:
                if hasattr(self.ai_core, "is_playing"):
                    if self.ai_core.is_playing.get(call_id, False):
                        self.ai_core.is_playing[call_id] = False
                        self.logger.info(
                            f"[PLAYBACK] Set is_playing[{call_id}] = False (playback failed in finally)"
                        )

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
        # ★関数の最初でログ★
        self.logger.warning(f"[INIT_METHOD_ENTRY] Called with client_id={client_id}")
        try:
            # 【追加】タスク開始ログ
            self.logger.warning(f"[INIT_TASK] Task started for client_id={client_id}")
            # 【診断用】強制的に可視化
            effective_call_id = self._get_effective_call_id()
            self.logger.warning(
                f"[DEBUG_PRINT] _queue_initial_audio_sequence called client_id={client_id} call_id={effective_call_id}"
            )

            # 【追加】二重実行ガード（通話ごとのフラグチェック）
            if effective_call_id and effective_call_id in self._initial_sequence_played:
                self.logger.warning(
                    f"[INIT_SEQ] Skipping initial sequence for {effective_call_id} (already played)."
                )
                return

            effective_client_id = client_id or self.default_client_id
            if not effective_client_id:
                self.logger.warning("[INIT_DEBUG] No effective_client_id, returning early")
                return

            # 無音監視基準時刻を初期化（通話開始時）
            effective_call_id = self._get_effective_call_id()

            # 【追加】effective_call_idが確定した時点で再度チェック
            if effective_call_id and effective_call_id in self._initial_sequence_played:
                self.logger.warning(
                    f"[INIT_SEQ] Skipping initial sequence for {effective_call_id} (already played, checked after call_id resolution)."
                )
                return

            # ★フラグセットは削除（キュー追加成功後に移動）★

            if effective_call_id:
                current_time = time.monotonic()
                self._last_tts_end_time[effective_call_id] = current_time
                self._last_user_input_time[effective_call_id] = current_time
                # アクティブな通話として登録（重複登録を防ぐ）
                if effective_call_id not in self._active_calls:
                    self.logger.warning(
                        f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls (_queue_initial_audio_sequence) at {time.time():.3f}"
                    )
                    self._active_calls.add(effective_call_id)
                self.logger.debug(
                    f"[CALL_START] Initialized silence monitoring timestamps for call_id={effective_call_id}"
                )

            # AICore.on_call_start() を呼び出し（クライアント001専用のテンプレート000-002を再生）
            self.logger.warning(
                f"[DEBUG_PRINT] checking on_call_start: hasattr={hasattr(self.ai_core, 'on_call_start')}"
            )
            if hasattr(self.ai_core, "on_call_start"):
                try:
                    self.logger.warning(
                        f"[DEBUG_PRINT] calling on_call_start call_id={effective_call_id} client_id={effective_client_id}"
                    )
                    self.ai_core.on_call_start(effective_call_id, client_id=effective_client_id)
                    self.logger.warning("[DEBUG_PRINT] on_call_start returned successfully")
                    self.logger.info(
                        f"[CALL_START] on_call_start() called for call_id={effective_call_id} client_id={effective_client_id}"
                    )
                except Exception as e:
                    self.logger.warning(f"[DEBUG_PRINT] on_call_start exception: {e}")
                    self.logger.exception(
                        f"[CALL_START] Error calling on_call_start(): {e}"
                    )
            else:
                self.logger.warning("[DEBUG_PRINT] on_call_start method not found in ai_core")

            # ★ここでログ出力★
            self.logger.warning(
                f"[INIT_DEBUG] Calling play_incoming_sequence for client={effective_client_id}"
            )
            try:
                # 同期関数をスレッドプールで実行（I/Oブロッキングを回避）
                # ★タイムアウト設定（3秒）★
                self.logger.warning(
                    f"[INIT_TIMEOUT_START] Starting wait_for with timeout=3.0 for client={effective_client_id}"
                )
                loop = asyncio.get_running_loop()
                audio_paths = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, self.audio_manager.play_incoming_sequence, effective_client_id
                    ),
                    timeout=3.0,
                )
                # 【追加】デバッグログ：audio_pathsの取得結果を詳細に出力
                self.logger.warning(
                    f"[INIT_TIMEOUT_SUCCESS] play_incoming_sequence completed within timeout for {effective_client_id}"
                )
                self.logger.warning(
                    f"[INIT_DEBUG] audio_paths result: {[str(p) for p in audio_paths]} (count={len(audio_paths)})"
                )
            except asyncio.TimeoutError:
                self.logger.error(
                    f"[INIT_ERR] Initial sequence timed out for client={effective_client_id} (timeout=3.0s)"
                )
                self.logger.error(
                    f"[INIT_TIMEOUT_ERROR] asyncio.TimeoutError caught for client={effective_client_id}"
                )
                # タイムアウト時は空リストとして扱う
                audio_paths = []
            except Exception as e:
                self.logger.error(
                    f"[INIT_ERR] Failed to load incoming sequence for client={effective_client_id}: {e}"
                )
                self.logger.error(
                    f"[INIT_EXCEPTION] Exception type: {type(e).__name__} for client={effective_client_id}"
                )
                self.logger.error(
                    f"[INIT_EXCEPTION] Exception details: {str(e)}", exc_info=True
                )
                return
            finally:
                self.logger.warning(
                    f"[INIT_FINALLY] Finally block reached for client={effective_client_id}"
                )

            if audio_paths:
                self.logger.info(
                    "[client=%s] initial greeting files=%s",
                    effective_client_id,
                    [str(p) for p in audio_paths],
                )
            else:
                self.logger.warning(
                    f"[client={effective_client_id}] No audio files found for initial sequence"
                )

            chunk_size = 160
            queued_chunks = 0
            queue_labels = []

            # 1) 0.5秒の無音を000よりも前に必ず積む（RTP開始時のノイズ防止）
            silence_payload = self._generate_silence_ulaw(self.initial_silence_sec)
            silence_samples = len(silence_payload)
            silence_chunks = 0
            for i in range(0, len(silence_payload), chunk_size):
                self.tts_queue.append(silence_payload[i : i + chunk_size])
                silence_chunks += 1
                queued_chunks += 1
            if silence_chunks:
                queue_labels.append(f"silence({self.initial_silence_sec:.1f}s)")
                self.logger.info(
                    "[client=%s] initial silence queued samples=%d chunks=%d duration=%.3fs",
                    effective_client_id,
                    silence_samples,
                    silence_chunks,
                    silence_samples / 8000.0,
                )

            file_entries = []
            for idx, audio_path in enumerate(audio_paths):
                # 【追加】デバッグログ：各ファイルの処理状況を詳細に出力
                self.logger.warning(
                    f"[INIT_DEBUG] Processing audio_path[{idx}]={audio_path} exists={audio_path.exists()}"
                )
                if not audio_path.exists():
                    self.logger.warning(
                        f"[client={effective_client_id}] audio file missing: {audio_path}"
                    )
                    continue
                try:
                    ulaw_payload = self._load_wav_as_ulaw8k(audio_path)
                    self.logger.warning(
                        f"[INIT_DEBUG] Loaded audio_path[{idx}]={audio_path} payload_len={len(ulaw_payload)}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"[client={effective_client_id}] failed to prepare {audio_path}: {e}"
                    )
                    continue
                size = None
                try:
                    size = audio_path.stat().st_size
                except OSError:
                    size = None
                try:
                    rel = str(audio_path.relative_to(_PROJECT_ROOT))
                except ValueError:
                    rel = str(audio_path)
                file_entries.append({"path": rel, "size": size})

                queue_labels.append(audio_path.stem)
                # 2) クライアント設定順（例: 000→001→002）に従い各ファイルを順番に積む
                for i in range(0, len(ulaw_payload), chunk_size):
                    self.tts_queue.append(ulaw_payload[i : i + chunk_size])
                    queued_chunks += 1

            if file_entries:
                self.logger.info(
                    "[client=%s] initial greeting files=%s",
                    effective_client_id,
                    file_entries,
                )

            if queue_labels:
                pretty_order = " -> ".join(queue_labels)
                pretty_paths = " -> ".join(str(p) for p in audio_paths) or "n/a"
                self.logger.info(
                    "[client=%s] initial queue order=%s (paths=%s)",
                    effective_client_id,
                    pretty_order,
                    pretty_paths,
                )

            if queued_chunks:
                # ★キュー追加成功後、ここで初めてフラグを立てる★
                if effective_call_id:
                    self._initial_sequence_played.add(effective_call_id)
                    self.logger.warning(
                        f"[INIT_SEQ] Flag set for {effective_call_id}. Queued {queued_chunks} chunks."
                    )

                self.is_speaking_tts = True
                self.initial_sequence_played = True
                self.initial_sequence_playing = True  # 初回シーケンス再生中フラグを立てる
                self.initial_sequence_completed = False
                self.initial_sequence_completed_time = None
                self.logger.info(
                    "[INITIAL_SEQUENCE] ON: client=%s initial_sequence_playing=True (ASR will be disabled during playback)",
                    effective_client_id,
                )
                self.logger.info(
                    "[client=%s] initial greeting enqueued (%d chunks)",
                    effective_client_id,
                    queued_chunks,
                )
            else:
                # キューに追加できなかった場合
                self.logger.warning(
                    f"[INIT_SEQ] No chunks queued for {effective_call_id}. Flag NOT set."
                )
        except Exception as e:
            # ★エラーをキャッチしてログ出しし、ここで止める（伝播させない）★
            self.logger.error(
                f"[INIT_ERR] Critical error in initial sequence: {e}\n{traceback.format_exc()}"
            )

    def _load_wav_as_ulaw8k(self, wav_path: Path) -> bytes:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if n_channels > 1:
            frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
        if sample_width != 2:
            frames = audioop.lin2lin(frames, sample_width, 2)
            sample_width = 2
        if framerate != 8000:
            frames, _ = audioop.ratecv(frames, sample_width, 1, framerate, 8000, None)
        return audioop.lin2ulaw(frames, sample_width)

    def _generate_silence_ulaw(self, duration_sec: float) -> bytes:
        samples = max(1, int(8000 * duration_sec))
        pcm16_silence = b"\x00\x00" * samples
        return audioop.lin2ulaw(pcm16_silence, 2)

    async def _flush_tts_queue(self) -> None:
        await self.tts_sender._flush_tts_queue()

    async def _tts_sender_loop(self) -> None:
        await self.tts_sender._tts_sender_loop()

    async def _handle_playback_start(self, call_id: str, audio_file: str) -> None:
        await self.controller.handle_playback_start(call_id, audio_file)

    async def _handle_playback_stop(self, call_id: str) -> None:
        await self.controller.handle_playback_stop(call_id)
