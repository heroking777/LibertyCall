"""Playback handler for core playback execution."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.playback_manager import GatewayPlaybackManager


class PlaybackHandler:
    def __init__(self, manager: "GatewayPlaybackManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def handle_playback(self, call_id: str, audio_file: str) -> None:
        manager = self.manager
        # 【修正】call_idが_active_callsに存在しない場合は自動追加
        if not hasattr(manager, "_active_calls"):
            manager._active_calls = set()
        elif not manager._active_calls:
            manager._active_calls = set()

        if call_id not in manager._active_calls:
            # call_uuid_mapでUUID→call_id変換を試す
            call_id_found = False
            if hasattr(manager, "call_uuid_map"):
                for mapped_call_id, mapped_uuid in manager.call_uuid_map.items():
                    if mapped_uuid == call_id and mapped_call_id in manager._active_calls:
                        call_id_found = True
                        self.logger.info(
                            "[PLAYBACK] Found call_id via UUID mapping: %s -> %s",
                            call_id,
                            mapped_call_id,
                        )
                        break

            if not call_id_found:
                # 自動追加（再生リクエストがある = 通話がアクティブ）
                self.logger.info(
                    "[PLAYBACK] Auto-adding call_id=%s to _active_calls (playback request received, current active_calls: %s)",
                    call_id,
                    manager._active_calls,
                )
                manager._active_calls.add(call_id)

        try:
            # ESL接続が切れている場合は自動リカバリを試みる
            if not manager.esl_connection or not manager.esl_connection.connected():
                self.logger.warning(
                    "[PLAYBACK] ESL not available, attempting recovery: call_id=%s file=%s",
                    call_id,
                    audio_file,
                )
                manager._recover_esl_connection()

                # 再接続に失敗した場合はスキップ
                if not manager.esl_connection or not manager.esl_connection.connected():
                    self.logger.error(
                        "[PLAYBACK] ESL recovery failed, skipping playback: call_id=%s file=%s",
                        call_id,
                        audio_file,
                    )
                    return

            # 再生開始: is_playing[uuid] = True を設定
            if hasattr(manager.ai_core, "is_playing"):
                manager.ai_core.is_playing[call_id] = True
                self.logger.info("[PLAYBACK] is_playing[%s] = True", call_id)

            # 【修正1】再生前のUUID先読み更新（Pre-emptive Update）
            # call_idからFreeSWITCH UUIDに変換（マッピングが存在する場合）
            freeswitch_uuid = manager.call_uuid_map.get(call_id, call_id)

            # UUIDの有効性を事前確認（先読み更新）
            # 【修正1】より積極的にUUID更新を実行（常にUUID更新を試行）
            uuid_needs_update = True  # 常にUUID更新を試行

            if uuid_needs_update:
                self.logger.info(
                    "[PLAYBACK] Pre-emptive UUID update: call_id=%s current_uuid=%s",
                    call_id,
                    freeswitch_uuid,
                )
                # UUIDを先読み更新
                new_uuid = None
                if hasattr(manager, "fs_rtp_monitor") and manager.fs_rtp_monitor:
                    new_uuid = manager.fs_rtp_monitor.update_uuid_mapping_for_call(call_id)

                if not new_uuid:
                    self.logger.info(
                        "[PLAYBACK] Pre-emptive UUID lookup: executing direct lookup for call_id=%s",
                        call_id,
                    )
                    new_uuid = manager._update_uuid_mapping_directly(call_id)

                if new_uuid:
                    freeswitch_uuid = new_uuid
                    self.logger.info(
                        "[PLAYBACK] Pre-emptive UUID update successful: call_id=%s -> uuid=%s",
                        call_id,
                        freeswitch_uuid,
                    )
                else:
                    self.logger.warning(
                        "[PLAYBACK] Pre-emptive UUID update failed, using current UUID: call_id=%s uuid=%s",
                        call_id,
                        freeswitch_uuid,
                    )
            else:
                self.logger.debug(
                    "[PLAYBACK] Using mapped UUID: call_id=%s -> uuid=%s",
                    call_id,
                    freeswitch_uuid,
                )

            # 【修正3】110連打防止: 再生リクエスト送信時にlast_activityを更新（成否に関わらず）
            # 再生リクエスト送信直前で更新することで、リクエストの成否に関わらずタイマーをリセット
            if hasattr(manager.ai_core, "last_activity"):
                manager.ai_core.last_activity[call_id] = time.time()
                self.logger.info(
                    "[PLAYBACK] Updated last_activity on request: call_id=%s (preventing timeout loop)",
                    call_id,
                )

            # ESLを使ってuuid_playbackを実行（非同期実行で応答速度を最適化）
            result = manager.esl_connection.execute(
                "playback", audio_file, uuid=freeswitch_uuid, force_async=True
            )

            playback_success = False
            invalid_session = False
            # 【修正3】再生成功フラグをselfに保存（finallyブロックでアクセス可能にする）
            manager._last_playback_success = False
            if result:
                reply_text = (
                    result.getHeader("Reply-Text") if hasattr(result, "getHeader") else None
                )
                if reply_text and "+OK" in reply_text:
                    playback_success = True
                    manager._last_playback_success = True
                    self.logger.info(
                        "[PLAYBACK] Playback started: call_id=%s file=%s uuid=%s",
                        call_id,
                        audio_file,
                        freeswitch_uuid,
                    )
                else:
                    # invalid session idエラーを検知
                    if reply_text and "invalid session id" in reply_text.lower():
                        invalid_session = True
                        # 【修正3】invalid session id検出時は最大3回までリトライ
                        if not hasattr(manager, "_playback_retry_count"):
                            manager._playback_retry_count = {}
                        retry_count = manager._playback_retry_count.get(call_id, 0)
                        if retry_count < 3:
                            self.logger.warning(
                                "[PLAYBACK] Invalid session id detected: call_id=%s uuid=%s reply=%s (retry %s/3)",
                                call_id,
                                freeswitch_uuid,
                                reply_text,
                                retry_count + 1,
                            )
                        else:
                            self.logger.error(
                                "[PLAYBACK] Invalid session id detected: call_id=%s uuid=%s reply=%s (max retries exceeded)",
                                call_id,
                                freeswitch_uuid,
                                reply_text,
                            )
                    else:
                        self.logger.warning(
                            "[PLAYBACK] Playback command may have failed: call_id=%s reply=%s",
                            call_id,
                            reply_text,
                        )
            else:
                self.logger.warning("[PLAYBACK] No response from ESL: call_id=%s", call_id)

            # 【修正3】invalid session idエラー時、UUIDマッピングを再取得してリトライ（最大3回まで）
            if invalid_session:
                # リトライカウントを初期化（まだ存在しない場合）
                if not hasattr(manager, "_playback_retry_count"):
                    manager._playback_retry_count = {}
                retry_count = manager._playback_retry_count.get(call_id, 0)
                max_retries = 3

                if retry_count < max_retries:
                    # リトライカウントを増加
                    manager._playback_retry_count[call_id] = retry_count + 1
                    self.logger.info(
                        "[PLAYBACK] Attempting UUID remapping for call_id=%s (retry %s/%s)",
                        call_id,
                        retry_count + 1,
                        max_retries,
                    )
                # 【修正1】UUIDマッピングを再取得（fs_rtp_monitorを使用、見つからない場合はRealtimeGateway自身が実行）
                new_uuid = None
                if hasattr(manager, "fs_rtp_monitor") and manager.fs_rtp_monitor:
                    new_uuid = manager.fs_rtp_monitor.update_uuid_mapping_for_call(call_id)

                # 【修正2】Monitorが見つからない場合でも、RealtimeGateway自身がshow channelsを実行
                if not new_uuid:
                    self.logger.info(
                        "[PLAYBACK] fs_rtp_monitor not available, executing UUID lookup directly: call_id=%s",
                        call_id,
                    )
                    new_uuid = manager._update_uuid_mapping_directly(call_id)
                    if new_uuid:
                        self.logger.info(
                            "[PLAYBACK] UUID remapped: call_id=%s -> new_uuid=%s (remapping successful)",
                            call_id,
                            new_uuid,
                        )
                        # 再取得したUUIDでリトライ
                        freeswitch_uuid = new_uuid
                        retry_result = manager.esl_connection.execute(
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
                                manager._last_playback_success = True
                                # リトライ成功時はカウントをリセット
                                manager._playback_retry_count[call_id] = 0
                                self.logger.info(
                                    "[PLAYBACK] Playback started (after remap): call_id=%s file=%s uuid=%s",
                                    call_id,
                                    audio_file,
                                    freeswitch_uuid,
                                )
                            else:
                                # リトライも失敗した場合、フォールバックを試みる（1回のみ）
                                if (
                                    retry_reply
                                    and "invalid session id" in retry_reply.lower()
                                ):
                                    self.logger.warning(
                                        "[PLAYBACK] Retry also failed with invalid session id: call_id=%s reply=%s",
                                        call_id,
                                        retry_reply,
                                    )
                                    # フォールバック: call_idを直接使用（これが最後の試み）
                                    self.logger.warning(
                                        "[PLAYBACK] Attempting final fallback: using call_id as UUID: call_id=%s",
                                        call_id,
                                    )
                                    freeswitch_uuid = call_id
                                    fallback_result = manager.esl_connection.execute(
                                        "playback",
                                        audio_file,
                                        uuid=freeswitch_uuid,
                                        force_async=True,
                                    )
                                    if fallback_result:
                                        fallback_reply = (
                                            fallback_result.getHeader("Reply-Text")
                                            if hasattr(fallback_result, "getHeader")
                                            else None
                                        )
                                        if fallback_reply and "+OK" in fallback_reply:
                                            playback_success = True
                                            manager._last_playback_success = True
                                            # リトライ成功時はカウントをリセット
                                            manager._playback_retry_count[call_id] = 0
                                            self.logger.info(
                                                "[PLAYBACK] Playback started (final fallback): call_id=%s file=%s uuid=%s",
                                                call_id,
                                                audio_file,
                                                freeswitch_uuid,
                                            )
                                        else:
                                            self.logger.error(
                                                "[PLAYBACK] Final fallback failed: call_id=%s reply=%s (no more retries)",
                                                call_id,
                                                fallback_reply,
                                            )
                                    else:
                                        self.logger.error(
                                            "[PLAYBACK] Final fallback failed: no response from ESL (no more retries)"
                                        )
                                else:
                                    self.logger.warning(
                                        "[PLAYBACK] Retry failed: call_id=%s reply=%s",
                                        call_id,
                                        retry_reply,
                                    )
                                    # リトライカウントをリセット（最大リトライ回数に達した場合）
                                    manager._playback_retry_count[call_id] = 0
                                    self.logger.error(
                                        "[PLAYBACK] Retry limit reached (max_retries=%s), aborting playback: call_id=%s",
                                        max_retries,
                                        call_id,
                                    )
                        else:
                            self.logger.warning(
                                "[PLAYBACK] Retry failed: no response from ESL"
                            )
                            # リトライカウントをリセット（最大リトライ回数に達した場合）
                            manager._playback_retry_count[call_id] = 0
                            self.logger.error(
                                "[PLAYBACK] Retry limit reached (max_retries=%s), aborting playback: call_id=%s",
                                max_retries,
                                call_id,
                            )
                else:
                    # 最大リトライ回数に達した場合
                    self.logger.error(
                        "[PLAYBACK] Max retries exceeded for call_id=%s (retry_count=%s, max_retries=%s)",
                        call_id,
                        retry_count,
                        max_retries,
                    )
                    # リトライカウントをリセット
                    manager._playback_retry_count[call_id] = 0

                # UUID再取得に失敗した場合の処理（retry_count < max_retries の外側で処理）
                if not new_uuid and retry_count < max_retries:
                    # UUID再取得に失敗した場合、call_idを直接使用（フォールバック、1回のみ）
                    self.logger.warning(
                        "[PLAYBACK] UUID remapping failed, using call_id as UUID (fallback): call_id=%s",
                        call_id,
                    )
                    freeswitch_uuid = call_id
                    fallback_result = manager.esl_connection.execute(
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
                            manager._last_playback_success = True
                            # リトライ成功時はカウントをリセット
                            manager._playback_retry_count[call_id] = 0
                            self.logger.info(
                                "[PLAYBACK] Playback started (fallback): call_id=%s file=%s uuid=%s",
                                call_id,
                                audio_file,
                                freeswitch_uuid,
                            )
                        else:
                            self.logger.error(
                                "[PLAYBACK] Fallback also failed: call_id=%s reply=%s (no more retries)",
                                call_id,
                                fallback_reply,
                            )
                    else:
                        self.logger.error(
                            "[PLAYBACK] Fallback failed: no response from ESL (no more retries)"
                        )
                else:
                    # UUID再取得に失敗した場合、call_idを直接使用（フォールバック、1回のみ）
                    self.logger.warning(
                        "[PLAYBACK] UUID remapping failed (both monitor and direct lookup), using call_id as UUID (fallback): call_id=%s",
                        call_id,
                    )
                    freeswitch_uuid = call_id
                    fallback_result = manager.esl_connection.execute(
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
                            manager._last_playback_success = True
                            self.logger.info(
                                "[PLAYBACK] Playback started (fallback): call_id=%s file=%s uuid=%s",
                                call_id,
                                audio_file,
                                freeswitch_uuid,
                            )
                        else:
                            self.logger.error(
                                "[PLAYBACK] Fallback also failed: call_id=%s reply=%s (no more retries)",
                                call_id,
                                fallback_reply,
                            )
                    else:
                        self.logger.error(
                            "[PLAYBACK] Fallback failed: no response from ESL (no more retries)"
                        )

            # 簡易実装: 音声ファイルの長さを推定して、その時間後にis_playingをFalseにする
            manager._schedule_playback_reset(call_id, audio_file)

        except Exception as exc:
            self.logger.exception("[PLAYBACK] Failed to send playback request: %s", exc)
            # 【修正3】エラー時はis_playingをFalseにする（次の発話認識をブロックしない）
            manager._last_playback_success = False
            if hasattr(manager.ai_core, "is_playing"):
                manager.ai_core.is_playing[call_id] = False
                self.logger.info(
                    "[PLAYBACK] Set is_playing[%s] = False (due to error)",
                    call_id,
                )
        finally:
            # 【修正3】再生リクエストの成否に関わらず、再生失敗時はis_playingをFalseに戻す
            # 再生成功時はis_playingをTrueのままにして、再生完了イベントでFalseにする
            # 再生失敗時（playback_successがFalse）の場合のみFalseに設定
            if (
                hasattr(manager, "_last_playback_success")
                and not manager._last_playback_success
            ):
                if hasattr(manager.ai_core, "is_playing"):
                    if manager.ai_core.is_playing.get(call_id, False):
                        manager.ai_core.is_playing[call_id] = False
                        self.logger.info(
                            "[PLAYBACK] Set is_playing[%s] = False (playback failed in finally)",
                            call_id,
                        )
