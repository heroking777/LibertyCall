#!/usr/bin/env python3
"""Call session handling for FreeSWITCH/Asterisk events."""
import asyncio
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from libertycall.client_loader import load_client_profile
from libertycall.gateway.client_mapper import resolve_client_id


OPERATOR_NUMBER = "08024152649"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GatewayCallSessionHandler:
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        self.logger = gateway.logger

    async def _handle_init_from_asterisk(self, data: dict):
        """
        Asteriskからのinitメッセージを処理（クライアントID自動判定対応）
        """
        req_call_id = data.get("call_id")
        req_caller_number = data.get("caller_number")
        req_destination_number = data.get("destination_number")  # 着信番号（将来実装）
        req_sip_headers = data.get("sip_headers")  # SIPヘッダ（将来実装）

        # caller_numberをログで確認（最初に記録）
        self.logger.info(
            f"[Init from Asterisk] caller_number received: {req_caller_number}"
        )

        # クライアントID自動判定（優先順位: 明示指定 > SIPヘッダ > 着信番号 > 発信者番号 > デフォルト）
        explicit_client_id = data.get("client_id")
        if explicit_client_id:
            req_client_id = explicit_client_id
            self.logger.info(
                f"[Init from Asterisk] Using explicit client_id: {req_client_id}"
            )
        else:
            # 自動判定
            req_client_id = resolve_client_id(
                caller_number=req_caller_number,
                destination_number=req_destination_number,
                sip_headers=req_sip_headers,
                fallback=self.gateway.default_client_id,
            )
            self.logger.info(
                "[Init from Asterisk] Auto-resolved client_id: %s "
                "(caller=%s, dest=%s)",
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
            self.gateway.client_profile = load_client_profile(req_client_id)
        except FileNotFoundError as e:
            self.logger.warning(
                f"[Init from Asterisk] Config file not found for {req_client_id}, "
                f"using default: {e}"
            )
            # デフォルト設定を使用
            self.gateway.client_profile = {
                "client_id": req_client_id,
                "base_dir": f"/opt/libertycall/clients/{req_client_id}",
                "log_dir": f"/opt/libertycall/logs/calls/{req_client_id}",
                "config": {
                    "client_name": "Default",
                    "save_calls": True,
                },
                "rules": {},
            }
        except Exception as e:
            self.logger.error(
                f"[Init from Asterisk] Failed to load client profile: {e}",
                exc_info=True,
            )
            # エラー時もデフォルト設定を使用して処理を続行
            self.gateway.client_profile = {
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
            if self.gateway.call_id and (
                self.gateway.client_id != req_client_id
                or (req_call_id and self.gateway.call_id != req_call_id)
            ):
                self.gateway._complete_console_call()
            self.gateway._reset_call_state()
            self.gateway.client_id = req_client_id
            self.gateway.config = self.gateway.client_profile["config"]
            self.gateway.rules = self.gateway.client_profile["rules"]

            # caller_numberをAICoreに設定（config読み込み失敗時も必ず実行）
            # "-" や空文字列の場合は None に変換
            if (
                req_caller_number
                and req_caller_number.strip()
                and req_caller_number not in ("-", "")
            ):
                self.gateway.ai_core.caller_number = req_caller_number.strip()
                self.logger.info(
                    f"[Init from Asterisk] Set caller_number: {req_caller_number.strip()}"
                )
            else:
                self.gateway.ai_core.caller_number = None
                self.logger.warning(
                    "[Init from Asterisk] caller_number not provided or invalid "
                    f"(received: {req_caller_number})"
                )

            # caller_numberをログで確認（DB保存前）
            caller_number_for_db = getattr(self.gateway.ai_core, "caller_number", None)
            self.logger.info(
                f"[Init from Asterisk] caller_number for DB: {caller_number_for_db}"
            )

            # DB保存処理（config読み込み失敗時も必ず実行）
            self.gateway._ensure_console_session(call_id_override=req_call_id)

            # caller_numberがDBに保存されたことをログで確認
            if caller_number_for_db:
                self.logger.info(
                    f"[Init from Asterisk] caller_number saved to DB: {caller_number_for_db}"
                )

            # 管理画面用に通話情報を明示的にログ出力（call_id / caller_number / timestamp）
            try:
                now_ts = datetime.now().isoformat()
                self.logger.info(
                    "[CallInfo] call_id=%s caller=%s timestamp=%s status=in_progress",
                    self.gateway.call_id or req_call_id,
                    caller_number_for_db,
                    now_ts,
                )
            except Exception as e:
                self.logger.warning(
                    f"[CallInfo] failed to log call info for UI: {e}"
                )

            # 非同期タスクとして実行（結果を待たない）
            task = asyncio.create_task(
                self.gateway._queue_initial_audio_sequence(self.gateway.client_id)
            )

            def _log_init_task_result(t):
                try:
                    t.result()  # 例外があればここで再送出される
                except Exception as e:
                    import traceback

                    self.logger.error(
                        f"[INIT_TASK_ERR] Initial sequence task failed: {e}\n"
                        f"{traceback.format_exc()}"
                    )

            task.add_done_callback(_log_init_task_result)
            self.logger.warning(f"[INIT_TASK_START] Created task for {self.gateway.client_id}")

            self.logger.debug(
                f"[Init from Asterisk] Loaded: {self.gateway.config.get('client_name', 'Default')}"
            )

            # 【デバッグ】無音タイマー設定をログ出力
            self.logger.info(
                "[DEBUG_INIT] No-input timer settings: NO_INPUT_TIMEOUT=%ss, "
                "MAX_NO_INPUT_TIME=%ss, NO_INPUT_STREAK_LIMIT=%s",
                self.gateway.NO_INPUT_TIMEOUT,
                self.gateway.MAX_NO_INPUT_TIME,
                self.gateway.NO_INPUT_STREAK_LIMIT,
            )

            # 通話開始時点では無音検知タイマーを起動しない
            # （初期アナウンス再生完了後に起動する）
            # effective_call_id = self.call_id or req_call_id
            # if effective_call_id:
            #     self.logger.debug(f"[DEBUG_INIT] Starting no_input_timer at call start for call_id={effective_call_id}")
            #     self._start_no_input_timer(effective_call_id)
        except Exception as e:
            self.logger.error(
                f"[Init from Asterisk] Error during initialization: {e}",
                exc_info=True,
            )
            # エラーが発生してもcaller_numberの設定とDB保存だけは試みる
            if (
                req_caller_number
                and req_caller_number.strip()
                and req_caller_number not in ("-", "")
            ):
                self.gateway.ai_core.caller_number = req_caller_number.strip()
                self.logger.info(
                    "[Init from Asterisk] Set caller_number (fallback): %s",
                    req_caller_number.strip(),
                )
                # 最小限のDB保存処理を試みる
                try:
                    self.gateway._ensure_console_session(call_id_override=req_call_id)
                    self.logger.info(
                        "[Init from Asterisk] caller_number saved to DB (fallback): %s",
                        req_caller_number.strip(),
                    )
                except Exception as db_error:
                    self.logger.error(
                        f"[Init from Asterisk] Failed to save caller_number to DB: {db_error}",
                        exc_info=True,
                    )

    def _handle_transfer(self, call_id: str) -> None:
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
                except Exception as e:
                    self.logger.warning(
                        "TRANSFER_TO_OPERATOR: handoff_redirect wait failed pid=%s call_id=%s error=%s",
                        proc.pid,
                        gateway.call_id,
                        e,
                    )

            threading.Thread(
                target=wait_for_process,
                daemon=True,
                name=f"wait-handoff-{proc.pid}",
            ).start()

        except Exception as e:
            self.logger.exception(
                "TRANSFER_TO_OPERATOR_FAILED: Failed to spawn handoff_redirect call_id=%s error=%r",
                gateway.call_id,
                e,
            )

        gateway.transfer_notified = True
        self.logger.info(
            "TRANSFER_TO_OPERATOR_DONE: call_id=%s transfer_notified=True",
            gateway.call_id,
        )

    def _update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
        """
        RealtimeGateway自身がshow channelsを実行してUUIDを取得（Monitorに依存しない）

        :param call_id: 通話ID
        :return: 取得したUUID（失敗時はNone）
        """
        uuid = None

        # 方法1: RTP情報ファイルから取得（優先）
        try:
            rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
            if rtp_info_files:
                latest_file = max(rtp_info_files, key=lambda p: p.stat().st_mtime)
                with open(latest_file, "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.startswith("uuid="):
                            uuid = line.split("=", 1)[1].strip()
                            self.logger.info(
                                "[UUID_UPDATE] Found UUID from RTP info file: uuid=%s call_id=%s",
                                uuid,
                                call_id,
                            )
                            break
        except Exception as e:
            self.logger.debug(f"[UUID_UPDATE] Error reading RTP info file: {e}")

        # 方法2: show channelsから取得（フォールバック、call_idに紐付く正確なUUIDを抽出）
        if not uuid:
            try:
                result = subprocess.run(
                    ["fs_cli", "-x", "show", "channels"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) >= 2 and not lines[0].startswith("0 total"):
                        # UUID形式の正規表現（8-4-4-4-12形式）
                        uuid_pattern = (
                            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                            r"[0-9a-f]{4}-[0-9a-f]{12}$"
                        )
                        # 各行を解析してcall_idに一致するUUIDを探す
                        for line in lines[1:]:
                            if not line.strip() or line.startswith("uuid,"):
                                continue

                            parts = line.split(",")
                            if not parts or not parts[0].strip():
                                continue

                            # 先頭のUUIDを取得
                            candidate_uuid = parts[0].strip()
                            if not __import__("re").compile(uuid_pattern, __import__("re").IGNORECASE).match(
                                candidate_uuid
                            ):
                                continue

                            # call_idが行内に含まれているか確認（cid_name, name, presence_id等に含まれる可能性）
                            # call_idは通常 "in-YYYYMMDDHHMMSS" 形式
                            if call_id in line:
                                uuid = candidate_uuid
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from show channels (matched call_id): "
                                    "uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break

                        # call_idに一致するものが見つからなかった場合、最初の有効なUUIDを使用（フォールバック）
                        if not uuid:
                            for line in lines[1:]:
                                if not line.strip() or line.startswith("uuid,"):
                                    continue
                                parts = line.split(",")
                                if parts and parts[0].strip():
                                    candidate_uuid = parts[0].strip()
                                    if __import__("re").compile(uuid_pattern, __import__("re").IGNORECASE).match(
                                        candidate_uuid
                                    ):
                                        uuid = candidate_uuid
                                        self.logger.warning(
                                            "[UUID_UPDATE] Using first available UUID (call_id match failed): "
                                            "uuid=%s call_id=%s",
                                            uuid,
                                            call_id,
                                        )
                                        break
            except Exception as e:
                self.logger.warning(f"[UUID_UPDATE] Error getting UUID from show channels: {e}")

        # マッピングを更新
        if uuid and hasattr(self.gateway, "call_uuid_map"):
            old_uuid = self.gateway.call_uuid_map.get(call_id)
            self.gateway.call_uuid_map[call_id] = uuid
            if old_uuid != uuid:
                self.logger.info(
                    "[UUID_UPDATE] Updated mapping: call_id=%s old_uuid=%s -> new_uuid=%s",
                    call_id,
                    old_uuid,
                    uuid,
                )
            else:
                self.logger.debug(
                    "[UUID_UPDATE] Mapping unchanged: call_id=%s uuid=%s",
                    call_id,
                    uuid,
                )
            return uuid

        return None

    def update_uuid_mapping_for_call(self, call_id: str) -> Optional[str]:
        """
        call_idに対応するFreeSWITCH UUIDを取得してマッピングを更新

        :param call_id: 通話ID
        :return: 取得したUUID（失敗時はNone）
        """
        uuid = None

        # 方法1: RTP情報ファイルから取得（優先）
        try:
            # まず、既知のポートがあればポートベースで探す（より正確）
            port_candidates = []
            try:
                if (
                    hasattr(self.gateway, "fs_rtp_monitor")
                    and getattr(self.gateway.fs_rtp_monitor, "freeswitch_rtp_port", None)
                ):
                    port_candidates.append(self.gateway.fs_rtp_monitor.freeswitch_rtp_port)
            except Exception:
                pass
            try:
                if hasattr(self.gateway, "rtp_port") and self.gateway.rtp_port:
                    port_candidates.append(self.gateway.rtp_port)
            except Exception:
                pass

            for port in port_candidates:
                try:
                    found_uuid = self.gateway._find_rtp_info_by_port(port)
                    if found_uuid:
                        uuid = found_uuid
                        self.logger.info(
                            "[UUID_UPDATE] Found UUID from RTP info file by port: uuid=%s call_id=%s port=%s",
                            uuid,
                            call_id,
                            port,
                        )
                        break
                except Exception as e:
                    self.logger.debug(
                        "[UUID_UPDATE] Error during port-based RTP info search for port=%s: %s",
                        port,
                        e,
                    )

            # フォールバック: 既存の最終更新ファイルを参照してUUIDを取得
            if not uuid:
                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    latest_file = max(rtp_info_files, key=lambda p: p.stat().st_mtime)
                    with open(latest_file, "r") as f:
                        lines = f.readlines()
                        for line in lines:
                            if line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from RTP info file: uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break
        except Exception as e:
            self.logger.debug(f"[UUID_UPDATE] Error reading RTP info file: {e}")

        # 方法2: show channelsから取得（フォールバック、call_idに紐付く正確なUUIDを抽出）
        if not uuid:
            try:
                result = subprocess.run(
                    ["fs_cli", "-x", "show", "channels"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) >= 2 and not lines[0].startswith("0 total"):
                        # UUID形式の正規表現（8-4-4-4-12形式）
                        uuid_pattern = __import__("re").compile(
                            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                            r"[0-9a-f]{4}-[0-9a-f]{12}$",
                            __import__("re").IGNORECASE,
                        )

                        # 各行を解析してcall_idに一致するUUIDを探す
                        for line in lines[1:]:
                            if not line.strip() or line.startswith("uuid,"):
                                continue

                            parts = line.split(",")
                            if not parts or not parts[0].strip():
                                continue

                            # 先頭のUUIDを取得
                            candidate_uuid = parts[0].strip()
                            if not uuid_pattern.match(candidate_uuid):
                                continue

                            # call_idが行内に含まれているか確認（cid_name, name, presence_id等に含まれる可能性）
                            # call_idは通常 "in-YYYYMMDDHHMMSS" 形式
                            if call_id in line:
                                uuid = candidate_uuid
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from show channels (matched call_id): "
                                    "uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break

                        # call_idに一致するものが見つからなかった場合、最初の有効なUUIDを使用（フォールバック）
                        if not uuid:
                            for line in lines[1:]:
                                if not line.strip() or line.startswith("uuid,"):
                                    continue
                                parts = line.split(",")
                                if parts and parts[0].strip():
                                    candidate_uuid = parts[0].strip()
                                    if uuid_pattern.match(candidate_uuid):
                                        uuid = candidate_uuid
                                        self.logger.warning(
                                            "[UUID_UPDATE] Using first available UUID (call_id match failed): "
                                            "uuid=%s call_id=%s",
                                            uuid,
                                            call_id,
                                        )
                                        break
            except Exception as e:
                self.logger.warning(f"[UUID_UPDATE] Error getting UUID from show channels: {e}")

        # マッピングを更新
        if uuid and hasattr(self.gateway, "call_uuid_map"):
            old_uuid = self.gateway.call_uuid_map.get(call_id)
            self.gateway.call_uuid_map[call_id] = uuid
            if old_uuid != uuid:
                self.logger.info(
                    "[UUID_UPDATE] Updated mapping: call_id=%s old_uuid=%s -> new_uuid=%s",
                    call_id,
                    old_uuid,
                    uuid,
                )
            else:
                self.logger.debug(
                    "[UUID_UPDATE] Mapping unchanged: call_id=%s uuid=%s",
                    call_id,
                    uuid,
                )
            return uuid

        return None

    def _handle_hangup(self, call_id: str) -> None:
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
                "[FORCE_HANGUP] Disconnecting call_id=%s caller=%s after %.1fs of silence "
                "(streak=%s, MAX_NO_INPUT_TIME=%ss)",
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
                gateway.console_bridge.complete_call(gateway.call_id, ended_at=datetime.utcnow())
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
                    except Exception as e:
                        self.logger.warning(
                            "[FORCE_HANGUP] hangup_call wait failed pid=%s error=%s",
                            proc.pid,
                            e,
                        )

                threading.Thread(
                    target=wait_for_process,
                    daemon=True,
                    name=f"wait-hangup-{proc.pid}",
                ).start()

            except Exception as e:
                self.logger.exception(
                    "[FORCE_HANGUP] HANGUP_REQUEST_FAILED: Failed to spawn hangup_call "
                    "call_id=%s caller=%s error=%r",
                    gateway.call_id,
                    caller_number,
                    e,
                )

            self.logger.info("HANGUP_REQUEST_DONE: call_id=%s", gateway.call_id)
        except Exception as e:
            self.logger.error(
                "[HANGUP_ERR] Error during hangup for call_id=%s: %s",
                call_id_to_cleanup or call_id,
                e,
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
                    f"[CALL_CLEANUP] Cleared state for call_id={call_id_to_cleanup}"
                )

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
