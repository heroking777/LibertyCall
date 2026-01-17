"""Call lifecycle handling (init/transfer/hangup)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from libertycall.client_loader import load_client_profile
from libertycall.gateway.client_mapper import resolve_client_id

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.call_session_handler import GatewayCallSessionHandler


OPERATOR_NUMBER = "08024152649"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CallLifecycleHandler:
    def __init__(self, session_handler: "GatewayCallSessionHandler") -> None:
        self.session_handler = session_handler
        self.gateway = session_handler.gateway
        self.logger = session_handler.logger

    async def handle_init_from_asterisk(self, data: dict) -> None:
        """
        Asteriskからのinitメッセージを処理（クライアントID自動判定対応）
        """
        gateway = self.gateway
        req_call_id = data.get("call_id")
        req_caller_number = data.get("caller_number")
        req_destination_number = data.get("destination_number")  # 着信番号（将来実装）
        req_sip_headers = data.get("sip_headers")  # SIPヘッダ（将来実装）

        # caller_numberをログで確認（最初に記録）
        self.logger.info(
            "[Init from Asterisk] caller_number received: %s",
            req_caller_number,
        )

        # クライアントID自動判定（優先順位: 明示指定 > SIPヘッダ > 着信番号 > 発信者番号 > デフォルト）
        explicit_client_id = data.get("client_id")
        if explicit_client_id:
            req_client_id = explicit_client_id
            self.logger.info(
                "[Init from Asterisk] Using explicit client_id: %s",
                req_client_id,
            )
        else:
            # 自動判定
            req_client_id = resolve_client_id(
                caller_number=req_caller_number,
                destination_number=req_destination_number,
                sip_headers=req_sip_headers,
                fallback=gateway.default_client_id,
            )
            self.logger.info(
                "[Init from Asterisk] Auto-resolved client_id: %s (caller=%s, dest=%s)",
                req_client_id,
                req_caller_number,
                req_destination_number,
            )

        self.logger.debug(
            "[Init from Asterisk] client_id=%s, call_id=%s, caller_number=%s",
            req_client_id,
            req_call_id,
            req_caller_number,
        )

        # プロファイル読み込み（失敗時はデフォルト設定を使用）
        try:
            gateway.client_profile = load_client_profile(req_client_id)
        except FileNotFoundError as exc:
            self.logger.warning(
                "[Init from Asterisk] Config file not found for %s, using default: %s",
                req_client_id,
                exc,
            )
            # デフォルト設定を使用
            gateway.client_profile = {
                "client_id": req_client_id,
                "base_dir": f"/opt/libertycall/clients/{req_client_id}",
                "log_dir": f"/opt/libertycall/logs/calls/{req_client_id}",
                "config": {
                    "client_name": "Default",
                    "save_calls": True,
                },
                "rules": {},
            }
        except Exception as exc:
            self.logger.error(
                "[Init from Asterisk] Failed to load client profile: %s",
                exc,
                exc_info=True,
            )
            # エラー時もデフォルト設定を使用して処理を続行
            gateway.client_profile = {
                "client_id": req_client_id,
                "base_dir": f"/opt/libertycall/clients/{req_client_id}",
                "log_dir": f"/opt/libertycall/logs/calls/{req_client_id}",
                "config": {
                    "client_name": "Default",
                    "save_calls": True,
                },
                "rules": {},
            }

        # メモリ展開
        try:
            if gateway.call_id and (
                gateway.client_id != req_client_id
                or (req_call_id and gateway.call_id != req_call_id)
            ):
                gateway._complete_console_call()
            gateway._reset_call_state()
            gateway.client_id = req_client_id
            gateway.config = gateway.client_profile["config"]
            gateway.rules = gateway.client_profile["rules"]

            # caller_numberをAICoreに設定（config読み込み失敗時も必ず実行）
            # "-" や空文字列の場合は None に変換
            if (
                req_caller_number
                and req_caller_number.strip()
                and req_caller_number not in ("-", "")
            ):
                gateway.ai_core.caller_number = req_caller_number.strip()
                self.logger.info(
                    "[Init from Asterisk] Set caller_number: %s",
                    req_caller_number.strip(),
                )
            else:
                gateway.ai_core.caller_number = None
                self.logger.warning(
                    "[Init from Asterisk] caller_number not provided or invalid (received: %s)",
                    req_caller_number,
                )

            # caller_numberをログで確認（DB保存前）
            caller_number_for_db = getattr(gateway.ai_core, "caller_number", None)
            self.logger.info(
                "[Init from Asterisk] caller_number for DB: %s",
                caller_number_for_db,
            )

            # DB保存処理（config読み込み失敗時も必ず実行）
            gateway._ensure_console_session(call_id_override=req_call_id)

            # caller_numberがDBに保存されたことをログで確認
            if caller_number_for_db:
                self.logger.info(
                    "[Init from Asterisk] caller_number saved to DB: %s",
                    caller_number_for_db,
                )

            # 管理画面用に通話情報を明示的にログ出力（call_id / caller_number / timestamp）
            try:
                now_ts = datetime.now().isoformat()
                self.logger.info(
                    "[CallInfo] call_id=%s caller=%s timestamp=%s status=in_progress",
                    gateway.call_id or req_call_id,
                    caller_number_for_db,
                    now_ts,
                )
            except Exception as exc:
                self.logger.warning(
                    "[CallInfo] failed to log call info for UI: %s",
                    exc,
                )

            # 非同期タスクとして実行（結果を待たない）
            task = asyncio.create_task(
                gateway._queue_initial_audio_sequence(gateway.client_id)
            )

            def _log_init_task_result(t):
                try:
                    t.result()  # 例外があればここで再送出される
                except Exception as exc:
                    import traceback

                    self.logger.error(
                        "[INIT_TASK_ERR] Initial sequence task failed: %s\n%s",
                        exc,
                        traceback.format_exc(),
                    )

            task.add_done_callback(_log_init_task_result)
            self.logger.warning(
                "[INIT_TASK_START] Created task for %s",
                gateway.client_id,
            )

            self.logger.debug(
                "[Init from Asterisk] Loaded: %s",
                gateway.config.get("client_name", "Default"),
            )

            # 【デバッグ】無音タイマー設定をログ出力
            self.logger.info(
                "[DEBUG_INIT] No-input timer settings: NO_INPUT_TIMEOUT=%ss, MAX_NO_INPUT_TIME=%ss, NO_INPUT_STREAK_LIMIT=%s",
                gateway.NO_INPUT_TIMEOUT,
                gateway.MAX_NO_INPUT_TIME,
                gateway.NO_INPUT_STREAK_LIMIT,
            )

            # 通話開始時点では無音検知タイマーを起動しない
            # （初期アナウンス再生完了後に起動する）
            # effective_call_id = self.call_id or req_call_id
            # if effective_call_id:
            #     self.logger.debug(f"[DEBUG_INIT] Starting no_input_timer at call start for call_id={effective_call_id}")
            #     self._start_no_input_timer(effective_call_id)
        except Exception as exc:
            self.logger.error(
                "[Init from Asterisk] Error during initialization: %s",
                exc,
                exc_info=True,
            )
            # エラーが発生してもcaller_numberの設定とDB保存だけは試みる
            if (
                req_caller_number
                and req_caller_number.strip()
                and req_caller_number not in ("-", "")
            ):
                gateway.ai_core.caller_number = req_caller_number.strip()
                self.logger.info(
                    "[Init from Asterisk] Set caller_number (fallback): %s",
                    req_caller_number.strip(),
                )
                # 最小限のDB保存処理を試みる
                try:
                    gateway._ensure_console_session(call_id_override=req_call_id)
                    self.logger.info(
                        "[Init from Asterisk] caller_number saved to DB (fallback): %s",
                        req_caller_number.strip(),
                    )
                except Exception as db_error:
                    self.logger.error(
                        "[Init from Asterisk] Failed to save caller_number to DB: %s",
                        db_error,
                        exc_info=True,
                    )

    def handle_transfer(self, call_id: str) -> None:
        """
        転送処理を実行
        - console_bridge に転送を記録
        - ログに転送先番号を記録（Asterisk側での確認用）
        - Asterisk に channel redirect を指示
        """
        gateway = self.gateway
        self.logger.info(
            "TRANSFER_TO_OPERATOR_START: call_id=%s self.call_id=%s transfer_notified=%s",
            call_id,
            gateway.call_id,
            gateway.transfer_notified,
        )

        # transfer_notified のチェックを削除
        # 理由: 同じ通話内で複数回転送を試みる場合や、転送が失敗した場合に再試行できるようにするため
        # ただし、state.transfer_executed で二重実行を防ぐ（ai_core側で制御）
        if gateway.transfer_notified:
            self.logger.info(
                "TRANSFER_TO_OPERATOR_RETRY: call_id=%s previous_notified=True (allowing retry)",
                call_id,
            )
            # transfer_notified をリセットして再試行を許可
            gateway.transfer_notified = False

        # call_idが未設定の場合は正式なcall_idを生成（TEMP_CALLは使わない）
        if not gateway.call_id:
            if gateway.client_id:
                gateway.call_id = gateway.console_bridge.issue_call_id(gateway.client_id)
                self.logger.info(
                    "TRANSFER_TO_OPERATOR: generated call_id=%s (was None)",
                    gateway.call_id,
                )
                # AICoreにcall_idを設定
                if gateway.call_id:
                    gateway.ai_core.set_call_id(gateway.call_id)
            else:
                self.logger.warning(
                    "TRANSFER_TO_OPERATOR_SKIP: call_id=%s reason=no_self_call_id_and_no_client_id",
                    call_id,
                )
                # call_id パラメータがあれば、self.call_id に設定を試みる
                if call_id:
                    gateway.call_id = call_id
                    self.logger.info(
                        "TRANSFER_TO_OPERATOR: set self.call_id=%s from parameter",
                        call_id,
                    )
                else:
                    return

        state_label = f"AI_HANDOFF:{call_id or 'UNKNOWN'}"

        # 転送先番号をログに記録（Asterisk側での確認用）
        self.logger.info(
            "TRANSFER_TO_OPERATOR: call_id=%s target_number=%s",
            gateway.call_id,
            OPERATOR_NUMBER,
        )

        # ステップ1: 転送前に現在の会話ログを保存（call_idが既に設定されているので永続化済み）
        # 現在のcall_idで既にログが記録されているため、追加の保存処理は不要
        # ただし、caller_numberを確実に保持するために、ai_coreから取得して設定
        caller_number = getattr(gateway.ai_core, "caller_number", None)
        if caller_number and gateway.console_bridge.enabled:
            self.logger.info(
                "TRANSFER_TO_OPERATOR: preserving caller_number=%s for call_id=%s",
                caller_number,
                gateway.call_id,
            )

        # console_bridge に転送を記録
        if gateway.console_bridge.enabled:
            summary = gateway._build_handover_summary(state_label)
            gateway.console_bridge.mark_transfer(gateway.call_id, summary)
            self.logger.info(
                "TRANSFER_TO_OPERATOR: console_bridge marked transfer call_id=%s",
                gateway.call_id,
            )

        # Asterisk に handoff redirect を依頼（非同期で実行）
        # ステップ3: caller_numberを環境変数として渡して、handoff_redirect.pyで保持
        try:
            script_path = str(PROJECT_ROOT / "scripts" / "handoff_redirect.py")
            self.logger.info(
                "TRANSFER_TO_OPERATOR: Spawning handoff_redirect script_path=%s call_id=%s caller_number=%s",
                script_path,
                gateway.call_id,
                caller_number or "(none)",
            )
            # ステップ3: caller_numberを環境変数として渡して、handoff_redirect.pyで保持
            env = os.environ.copy()
            if caller_number:
                env["LC_CALLER_NUMBER"] = caller_number
            env["LC_CALL_ID"] = str(gateway.call_id)
            env["LC_CLIENT_ID"] = str(gateway.client_id or "000")

            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            self.logger.info(
                "TRANSFER_TO_OPERATOR: handoff_redirect spawned pid=%d call_id=%s",
                proc.pid,
                gateway.call_id,
            )

            # 非同期でwaitしてゾンビプロセスを防ぐ
            def wait_for_process():
                try:
                    proc.wait(timeout=30)
                    self.logger.info(
                        "TRANSFER_TO_OPERATOR: handoff_redirect completed pid=%s call_id=%s",
                        proc.pid,
                        gateway.call_id,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "TRANSFER_TO_OPERATOR: handoff_redirect wait failed pid=%s call_id=%s error=%s",
                        proc.pid,
                        gateway.call_id,
                        exc,
                    )

            threading.Thread(
                target=wait_for_process,
                daemon=True,
                name=f"wait-handoff-{proc.pid}",
            ).start()

        except Exception as exc:
            self.logger.exception(
                "TRANSFER_TO_OPERATOR_FAILED: Failed to spawn handoff_redirect call_id=%s error=%r",
                gateway.call_id,
                exc,
            )

        gateway.transfer_notified = True
        self.logger.info(
            "TRANSFER_TO_OPERATOR_DONE: call_id=%s transfer_notified=True",
            gateway.call_id,
        )

    def handle_hangup(self, call_id: str) -> None:
        """
        自動切断処理を実行
        - console_bridge に切断を記録
        - Asterisk に hangup を指示
        """
        gateway = self.gateway
        # 発信者番号を取得（ログ出力用）
        caller_number = getattr(gateway.ai_core, "caller_number", None) or "未設定"

        # クリーンアップ用のcall_idを確定（finallyブロックで使用）
        call_id_to_cleanup = None

        try:
            self.logger.warning(
                "[HANGUP_START] Processing hangup for call_id=%s self.call_id=%s",
                call_id,
                gateway.call_id,
            )

            self.logger.debug(
                "[FORCE_HANGUP] HANGUP_REQUEST: call_id=%s self.call_id=%s caller=%s",
                call_id,
                gateway.call_id,
                caller_number,
            )
            self.logger.info(
                "[FORCE_HANGUP] HANGUP_REQUEST: call_id=%s self.call_id=%s caller=%s",
                call_id,
                gateway.call_id,
                caller_number,
            )

            # call_id が未設定の場合はパラメータから設定
            if not gateway.call_id and call_id:
                gateway.call_id = call_id
                self.logger.info(
                    "[FORCE_HANGUP] HANGUP_REQUEST: set self.call_id=%s from parameter caller=%s",
                    call_id,
                    caller_number,
                )

            if not gateway.call_id:
                self.logger.warning(
                    "[FORCE_HANGUP] HANGUP_REQUEST_SKIP: call_id=%s caller=%s reason=no_self_call_id",
                    call_id,
                    caller_number,
                )
                return

            call_id_to_cleanup = gateway.call_id or call_id

            # 無音経過時間をログに記録
            elapsed = gateway._no_input_elapsed.get(gateway.call_id, 0.0)
            no_input_streak = 0
            state = gateway.ai_core._get_session_state(gateway.call_id)
            if state:
                no_input_streak = state.no_input_streak

            self.logger.warning(
                "[FORCE_HANGUP] Disconnecting call_id=%s caller=%s after %.1fs of silence (streak=%s, MAX_NO_INPUT_TIME=%ss)",
                gateway.call_id,
                caller_number,
                elapsed,
                no_input_streak,
                gateway.MAX_NO_INPUT_TIME,
            )

            # 録音を停止
            gateway._stop_recording()

            # console_bridge に切断を記録
            if gateway.console_bridge.enabled:
                gateway.console_bridge.complete_call(
                    gateway.call_id, ended_at=datetime.utcnow()
                )
                self.logger.info(
                    "[FORCE_HANGUP] console_bridge marked hangup call_id=%s caller=%s",
                    gateway.call_id,
                    caller_number,
                )

            # 明示的な通話終了処理（フラグクリア）
            if hasattr(gateway.ai_core, "on_call_end"):
                gateway.ai_core.on_call_end(call_id_to_cleanup, source="_handle_hangup")
            # 【追加】通話ごとのASRインスタンスをクリーンアップ
            if hasattr(gateway.ai_core, "cleanup_asr_instance"):
                gateway.ai_core.cleanup_asr_instance(call_id_to_cleanup)

            # Asterisk に hangup を依頼（非同期で実行）
            try:
                script_path = str(PROJECT_ROOT / "scripts" / "hangup_call.py")
                self.logger.info(
                    "[FORCE_HANGUP] HANGUP_REQUEST: Spawning hangup_call script_path=%s call_id=%s caller=%s",
                    script_path,
                    gateway.call_id,
                    caller_number,
                )
                proc = subprocess.Popen(
                    [sys.executable, script_path, gateway.call_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.logger.info(
                    "[FORCE_HANGUP] HANGUP_REQUEST: hangup_call spawned pid=%s call_id=%s caller=%s",
                    proc.pid,
                    gateway.call_id,
                    caller_number,
                )

                # 非同期でwaitしてゾンビプロセスを防ぐ
                def wait_for_process():
                    try:
                        proc.wait(timeout=30)
                        self.logger.info(
                            "[FORCE_HANGUP] hangup_call completed pid=%s call_id=%s",
                            proc.pid,
                            gateway.call_id,
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "[FORCE_HANGUP] hangup_call wait failed pid=%s error=%s",
                            proc.pid,
                            exc,
                        )

                threading.Thread(
                    target=wait_for_process,
                    daemon=True,
                    name=f"wait-hangup-{proc.pid}",
                ).start()

            except Exception as exc:
                self.logger.exception(
                    "[FORCE_HANGUP] HANGUP_REQUEST_FAILED: Failed to spawn hangup_call call_id=%s caller=%s error=%r",
                    gateway.call_id,
                    caller_number,
                    exc,
                )

            self.logger.info("HANGUP_REQUEST_DONE: call_id=%s", gateway.call_id)
        except Exception as exc:
            self.logger.error(
                "[HANGUP_ERR] Error during hangup for call_id=%s: %s",
                call_id_to_cleanup or call_id,
                exc,
                exc_info=True,
            )
        finally:
            # ★どんなエラーがあっても、ここは必ず実行する★
            self.logger.warning(
                "[FINALLY_BLOCK_ENTRY] Entered finally block for call_id=%s",
                call_id_to_cleanup or call_id,
            )
            if call_id_to_cleanup:
                cleanup_time = time.time()
                # _active_calls から削除
                self.logger.warning(
                    "[FINALLY_ACTIVE_CALLS] Before removal: call_id=%s in _active_calls=%s",
                    call_id_to_cleanup,
                    call_id_to_cleanup in gateway._active_calls
                    if hasattr(gateway, "_active_calls")
                    else False,
                )
                if (
                    hasattr(gateway, "_active_calls")
                    and call_id_to_cleanup in gateway._active_calls
                ):
                    gateway._active_calls.remove(call_id_to_cleanup)
                    self.logger.warning(
                        "[HANGUP_DONE] Removed %s from active_calls (finally block) at %.3f",
                        call_id_to_cleanup,
                        cleanup_time,
                    )
                self.logger.warning(
                    "[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id=%s in _active_calls=%s",
                    call_id_to_cleanup,
                    call_id_to_cleanup in gateway._active_calls
                    if hasattr(gateway, "_active_calls")
                    else False,
                )

                # 管理用データのクリーンアップ
                if call_id_to_cleanup in gateway._recovery_counts:
                    del gateway._recovery_counts[call_id_to_cleanup]
                if call_id_to_cleanup in gateway._initial_sequence_played:
                    gateway._initial_sequence_played.discard(call_id_to_cleanup)
                if call_id_to_cleanup in gateway._last_processed_sequence:
                    del gateway._last_processed_sequence[call_id_to_cleanup]
                gateway._last_voice_time.pop(call_id_to_cleanup, None)
                gateway._last_silence_time.pop(call_id_to_cleanup, None)
                gateway._last_tts_end_time.pop(call_id_to_cleanup, None)
                gateway._last_user_input_time.pop(call_id_to_cleanup, None)
                gateway._silence_warning_sent.pop(call_id_to_cleanup, None)
                if hasattr(gateway, "_initial_tts_sent"):
                    gateway._initial_tts_sent.discard(call_id_to_cleanup)
                self.logger.debug(
                    "[CALL_CLEANUP] Cleared state for call_id=%s",
                    call_id_to_cleanup,
                )
