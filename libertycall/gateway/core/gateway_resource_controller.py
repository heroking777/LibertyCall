"""Gateway resource (port/UUID mapping) helpers."""
from __future__ import annotations

import glob
import os
import socket
import subprocess
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.core.gateway_utils import GatewayUtils


class GatewayResourceController:
    def __init__(self, utils: "GatewayUtils") -> None:
        self.utils = utils
        self.gateway = utils.gateway
        self.logger = utils.logger

    def _free_port(self, port: int) -> None:
        """安全にポートを解放する（自分自身は殺さない）"""
        try:
            # まずポートが使用中かチェック
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                sock.close()
                self.logger.debug("[BOOT] Port %s is available", port)
                return  # ポートが空いているので何もしない
        except OSError as e:
            if e.errno == 98:  # Address already in use
                self.logger.warning(
                    "[BOOT] Port %s is in use, attempting to free it...", port
                )
                try:
                    # fuserでポートを使用しているプロセスのPIDを取得
                    res = subprocess.run(
                        ["fuser", f"{port}/tcp"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if not res.stdout.strip():
                        self.logger.debug(
                            "[BOOT] Port %s appears to be free now", port
                        )
                        return

                    # PIDを抽出（fuserの出力例: "9001/tcp: 12345 67890"）
                    pids = []
                    for part in res.stdout.strip().split():
                        # "9001/tcp:" や "12345" のような形式からPIDを抽出
                        if part.replace(":", "").replace("/", "").isdigit():
                            pid_str = part.replace(":", "").replace("/", "")
                            if pid_str.isdigit():
                                pids.append(int(pid_str))
                        elif part.isdigit():
                            pids.append(int(part))

                    # 自分自身のPIDを取得
                    current_pid = os.getpid()

                    # 自分自身を除外
                    target_pids = [pid for pid in pids if pid != current_pid]

                    if not target_pids:
                        self.logger.info(
                            "[BOOT] Port %s in use by current process only (PID %s) — skipping kill",
                            port,
                            current_pid,
                        )
                        return

                    # 自分以外のプロセスのみKILL
                    pid_strs = [str(pid) for pid in target_pids]
                    subprocess.run(
                        ["kill", "-9"] + pid_strs,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                    self.logger.info(
                        "[BOOT] Port %s freed by killing PIDs: %s",
                        port,
                        ", ".join(pid_strs),
                    )

                    # 少し待機してから再確認
                    time.sleep(0.5)
                except Exception as free_error:
                    self.logger.warning(
                        "[BOOT] Port free check failed: %s", free_error
                    )
            else:
                self.logger.warning("[BOOT] Error checking port %s: %s", port, e)

    def _update_uuid_mapping_directly(self, call_id: str) -> Optional[str]:
        return self.gateway.session_handler._update_uuid_mapping_directly(call_id)

    def _find_rtp_info_by_port(self, rtp_port: int) -> Optional[str]:
        """
        RTP port からファイルを探して UUID を返す

        :param rtp_port: RTP port番号
        :return: UUID または None
        """
        try:
            # 全ての rtp_info ファイルを検索
            rtp_info_files = glob.glob("/tmp/rtp_info_*.txt")

            self.logger.debug(
                "[RTP_INFO_SEARCH] port=%s total_files=%s",
                rtp_port,
                len(rtp_info_files),
            )

            for filepath in rtp_info_files:
                try:
                    with open(filepath, "r") as f:
                        content = f.read()

                        # port が含まれるかチェック（local または remote）
                        if f":{rtp_port}" in content:
                            # UUID を抽出
                            for line in content.split("\n"):
                                if line.startswith("uuid="):
                                    uuid = line.split("=", 1)[1].strip()
                                    self.logger.info(
                                        "[RTP_INFO_FOUND] port=%s file=%s uuid=%s",
                                        rtp_port,
                                        filepath,
                                        uuid,
                                    )
                                    return uuid

                except Exception as e:
                    self.logger.debug(
                        "[RTP_INFO_READ_ERROR] file=%s error=%s", filepath, e
                    )
                    continue

            self.logger.warning(
                "[RTP_INFO_NOT_FOUND] No file found for port=%s searched_files=%s",
                rtp_port,
                len(rtp_info_files),
            )
            return None

        except Exception as e:
            self.logger.exception(
                "[RTP_INFO_SEARCH_ERROR] port=%s error=%s", rtp_port, e
            )
            return None
