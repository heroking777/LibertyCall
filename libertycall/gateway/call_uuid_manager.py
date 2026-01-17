"""UUID mapping helpers for call sessions."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.call_session_handler import GatewayCallSessionHandler


class CallUUIDManager:
    def __init__(self, session_handler: "GatewayCallSessionHandler") -> None:
        self.session_handler = session_handler
        self.gateway = session_handler.gateway
        self.logger = session_handler.logger

    def update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
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
                with open(latest_file, "r") as file_obj:
                    lines = file_obj.readlines()
                    for line in lines:
                        if line.startswith("uuid="):
                            uuid = line.split("=", 1)[1].strip()
                            self.logger.info(
                                "[UUID_UPDATE] Found UUID from RTP info file: uuid=%s call_id=%s",
                                uuid,
                                call_id,
                            )
                            break
        except Exception as exc:
            self.logger.debug("[UUID_UPDATE] Error reading RTP info file: %s", exc)

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
                        uuid_pattern = re.compile(
                            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                            r"[0-9a-f]{4}-[0-9a-f]{12}$",
                            re.IGNORECASE,
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
                                    "[UUID_UPDATE] Found UUID from show channels (matched call_id): uuid=%s call_id=%s",
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
                                            "[UUID_UPDATE] Using first available UUID (call_id match failed): uuid=%s call_id=%s",
                                            uuid,
                                            call_id,
                                        )
                                        break
            except Exception as exc:
                self.logger.warning(
                    "[UUID_UPDATE] Error getting UUID from show channels: %s",
                    exc,
                )

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
                except Exception as exc:
                    self.logger.debug(
                        "[UUID_UPDATE] Error during port-based RTP info search for port=%s: %s",
                        port,
                        exc,
                    )

            # フォールバック: 既存の最終更新ファイルを参照してUUIDを取得
            if not uuid:
                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    latest_file = max(rtp_info_files, key=lambda p: p.stat().st_mtime)
                    with open(latest_file, "r") as file_obj:
                        lines = file_obj.readlines()
                        for line in lines:
                            if line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()
                                self.logger.info(
                                    "[UUID_UPDATE] Found UUID from RTP info file: uuid=%s call_id=%s",
                                    uuid,
                                    call_id,
                                )
                                break
        except Exception as exc:
            self.logger.debug("[UUID_UPDATE] Error reading RTP info file: %s", exc)

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
                        uuid_pattern = re.compile(
                            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                            r"[0-9a-f]{4}-[0-9a-f]{12}$",
                            re.IGNORECASE,
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
                                    "[UUID_UPDATE] Found UUID from show channels (matched call_id): uuid=%s call_id=%s",
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
                                            "[UUID_UPDATE] Using first available UUID (call_id match failed): uuid=%s call_id=%s",
                                            uuid,
                                            call_id,
                                        )
                                        break
            except Exception as exc:
                self.logger.warning(
                    "[UUID_UPDATE] Error getting UUID from show channels: %s",
                    exc,
                )

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
