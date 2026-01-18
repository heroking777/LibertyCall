"""RTP port parsing helpers for network manager."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.common.network_manager import GatewayNetworkManager


class NetworkPortParser:
    def __init__(self, manager: "GatewayNetworkManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def get_rtp_port_from_freeswitch(self) -> Optional[int]:
        """FreeSWITCHから現在の送信RTPポートを取得（RTP情報ファイル優先、uuid_dumpはフォールバック）"""
        # まず、RTP情報ファイルをチェック（Luaスクリプトが作成したファイル）
        try:
            rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
            if rtp_info_files:
                # 全ファイルを走査して、local= と uuid= を抽出し
                # 最終更新時刻が最新のファイルの情報を優先する
                candidate_port = None
                candidate_uuid = None
                candidate_mtime = 0.0
                for filepath in rtp_info_files:
                    try:
                        mtime = filepath.stat().st_mtime
                        with open(filepath, "r") as f:
                            content = f.read()
                        port = None
                        uuid = None
                        for line in content.splitlines():
                            if line.startswith("local="):
                                local_rtp = line.split("=", 1)[1].strip()
                                if ":" in local_rtp:
                                    port_str = local_rtp.split(":")[-1]
                                    try:
                                        port = int(port_str)
                                    except ValueError:
                                        self.logger.debug(
                                            "[FS_RTP_MONITOR] Failed to parse port in %s: %s",
                                            filepath,
                                            local_rtp,
                                        )
                                        port = None
                            elif line.startswith("uuid="):
                                uuid = line.split("=", 1)[1].strip()

                        if port and mtime >= candidate_mtime:
                            candidate_mtime = mtime
                            candidate_port = port
                            candidate_uuid = uuid
                            self.logger.info(
                                "[FS_RTP_MONITOR] Candidate RTP info: file=%s port=%s uuid=%s mtime=%s",
                                filepath,
                                port,
                                uuid,
                                mtime,
                            )
                    except Exception as e:
                        self.logger.debug(
                            "[FS_RTP_MONITOR] Error reading RTP info file %s: %s",
                            filepath,
                            e,
                        )

                if candidate_port:
                    self.logger.info(
                        "[FS_RTP_MONITOR] Selected RTP port %s (from RTP info files, latest matched)",
                        candidate_port,
                    )
                    # UUIDも見つかった場合は、gatewayのcall_uuid_mapに保存（最新のcall_idとマッピング）
                    if candidate_uuid and hasattr(self.manager.gateway, "call_uuid_map"):
                        # 最新のcall_idを取得（ai_coreから）
                        if hasattr(self.manager.gateway, "ai_core") and hasattr(
                            self.manager.gateway.ai_core, "call_id"
                        ):
                            latest_call_id = self.manager.gateway.ai_core.call_id
                            if latest_call_id:
                                try:
                                    pre_map = dict(self.manager.gateway.call_uuid_map)
                                except Exception:
                                    pre_map = {}
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTER] Registering uuid=%s for call_id=%s current_map=%s",
                                    candidate_uuid,
                                    latest_call_id,
                                    pre_map,
                                )
                                self.manager.gateway.call_uuid_map[latest_call_id] = candidate_uuid
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTERED] Updated map=%s",
                                    self.manager.gateway.call_uuid_map,
                                )
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Mapped call_id=%s -> uuid=%s",
                                    latest_call_id,
                                    candidate_uuid,
                                )
                    return candidate_port
        except Exception as e:
            self.logger.debug(
                "[FS_RTP_MONITOR] Error reading RTP info files (non-fatal): %s",
                e,
            )

        # フォールバック: uuid_dump経由で取得
        try:
            # まず show channels でアクティブなチャンネルのUUIDを取得
            result = subprocess.run(
                ["fs_cli", "-x", "show", "channels"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "[FS_RTP_MONITOR] fs_cli failed: %s", result.stderr
                )
                return None

            # CSV形式の出力からUUIDを抽出（最初の行はヘッダー、2行目以降がデータ）
            lines = result.stdout.strip().split("\n")
            if len(lines) < 2 or lines[0].startswith("0 total"):
                # チャンネルが存在しない
                return None

            # 2行目以降からUUIDを抽出（最初のカラムがUUID）
            uuid = None
            for line in lines[1:]:
                if line.strip() and not line.startswith("uuid,"):
                    parts = line.split(",")
                    if parts and parts[0].strip():
                        uuid = parts[0].strip()
                        break

            if not uuid:
                return None

            # uuid_dump でチャンネル変数を取得
            dump_result = subprocess.run(
                ["fs_cli", "-x", f"uuid_dump {uuid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if dump_result.returncode != 0:
                self.logger.warning(
                    "[FS_RTP_MONITOR] uuid_dump failed for %s (non-fatal): %s",
                    uuid,
                    dump_result.stderr,
                )
                return None

            # variable_rtp_local_port を検索（FreeSWITCH 1.10.12以降の形式）
            for line in dump_result.stdout.splitlines():
                if "variable_rtp_local_port" in line:
                    try:
                        port = int(line.split("=")[-1].strip())
                        self.logger.info(
                            "[FS_RTP_MONITOR] Found FreeSWITCH RTP port: %s (from uuid_dump of %s)",
                            port,
                            uuid,
                        )
                        return port
                    except (ValueError, IndexError):
                        self.logger.warning(
                            "[FS_RTP_MONITOR] Failed to parse variable_rtp_local_port from line: %s",
                            line,
                        )
                        continue

            # フォールバック: 旧形式の検索（後方互換性のため）
            port_matches = re.findall(
                r"(?:local_media_port|rtp_local_media_port)[:=]\s*(\d+)",
                dump_result.stdout,
            )
            if port_matches:
                port = int(port_matches[0])
                self.logger.info(
                    "[FS_RTP_MONITOR] Found FreeSWITCH RTP port: %s (from uuid_dump of %s, fallback format)",
                    port,
                    uuid,
                )
                return port

            self.logger.warning(
                "[FS_RTP_MONITOR] RTP port not found in uuid_dump output for %s",
                uuid,
            )
            self.logger.debug(
                "[FS_RTP_MONITOR] uuid_dump output: %s",
                dump_result.stdout[:500],
            )
            return None
        except Exception as e:
            self.logger.warning(
                "[FS_RTP_MONITOR] Error getting RTP port (non-fatal): %s",
                e,
            )
            return None
