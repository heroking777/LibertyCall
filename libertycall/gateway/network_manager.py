#!/usr/bin/env python3
"""Network/server handling for realtime gateway."""
import asyncio
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from libertycall.gateway.network_ws_handler import NetworkWSHandler
from libertycall.gateway.network_socket_server import NetworkSocketServer


class GatewayNetworkManager:
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        self.logger = gateway.logger
        self.ws_handler = NetworkWSHandler(self)
        self.socket_server = NetworkSocketServer(self)

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
                    if candidate_uuid and hasattr(self.gateway, "call_uuid_map"):
                        # 最新のcall_idを取得（ai_coreから）
                        if hasattr(self.gateway, "ai_core") and hasattr(
                            self.gateway.ai_core, "call_id"
                        ):
                            latest_call_id = self.gateway.ai_core.call_id
                            if latest_call_id:
                                try:
                                    pre_map = dict(self.gateway.call_uuid_map)
                                except Exception:
                                    pre_map = {}
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTER] Registering uuid=%s for call_id=%s current_map=%s",
                                    candidate_uuid,
                                    latest_call_id,
                                    pre_map,
                                )
                                self.gateway.call_uuid_map[latest_call_id] = candidate_uuid
                                self.logger.warning(
                                    "[DEBUG_UUID_REGISTERED] Updated map=%s",
                                    self.gateway.call_uuid_map,
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

    def _setup_server_socket(self) -> None:
        self.socket_server.setup_server_socket()

    def _cleanup_sockets(self) -> None:
        self.socket_server.cleanup_sockets()

    async def _log_monitor_loop(self):
        """
        ログファイルを監視し、HANDOFF_FAIL_TTS_REQUESTメッセージを検出してTTSアナウンスを送信
        """
        self.logger.debug("Log monitor loop started.")
        log_file = Path("/opt/libertycall/logs/realtime_gateway.log")
        processed_lines = set()  # 処理済みの行を記録（重複防止）

        # ログファイルが存在しない場合は作成を待つ
        if not log_file.exists():
            self.logger.warning("Gateway log file not found, waiting for creation...")
            while not log_file.exists() and self.gateway.running:
                await asyncio.sleep(1)

        # 起動時は現在のファイルサイズから開始（過去のログを読み込まない）
        if log_file.exists():
            last_position = log_file.stat().st_size
            self.logger.debug(
                "Log monitor: Starting from position %s (current file size)",
                last_position,
            )
        else:
            last_position = 0

        while self.gateway.running:
            try:
                if log_file.exists():
                    try:
                        with open(log_file, "r", encoding="utf-8") as f:
                            # 最後に読み取った位置に移動
                            f.seek(last_position)
                            new_lines = f.readlines()

                            # 新しい行を処理
                            for line in new_lines:
                                # 行のハッシュを計算して重複チェック
                                line_hash = hash(line.strip())
                                if line_hash in processed_lines:
                                    continue

                                if "[HANDOFF_FAIL_TTS_REQUEST]" in line:
                                    # メッセージをパース
                                    # フォーマット: [HANDOFF_FAIL_TTS_REQUEST] call_id=xxx text=xxx audio_len=xxx
                                    try:
                                        # call_idとtextを抽出
                                        call_id_match = re.search(r"call_id=([^\s]+)", line)
                                        # text='...' または text="..." の形式を抽出
                                        text_match_quoted = re.search(
                                            r"text=([\"'])(.*?)\1", line
                                        )
                                        text_match_unquoted = re.search(
                                            r"text=([^\s]+)", line
                                        )

                                        if call_id_match:
                                            call_id = call_id_match.group(1)
                                            # 引用符で囲まれたテキストを優先、なければ引用符なしのテキスト
                                            if text_match_quoted:
                                                text = text_match_quoted.group(2)
                                            elif text_match_unquoted:
                                                text = text_match_unquoted.group(1)
                                            else:
                                                self.logger.warning(
                                                    "HANDOFF_FAIL_TTS: Failed to extract text from line: %s",
                                                    line,
                                                )
                                                processed_lines.add(line_hash)
                                                continue

                                            # 現在の通話でない場合は無視（call_idが一致しない、または通話が開始されていない）
                                            effective_call_id = (
                                                self.gateway._get_effective_call_id()
                                            )
                                            if call_id != effective_call_id:
                                                self.logger.debug(
                                                    "HANDOFF_FAIL_TTS_SKIP: call_id mismatch (request=%s, current=%s)",
                                                    call_id,
                                                    effective_call_id,
                                                )
                                                processed_lines.add(line_hash)
                                                continue

                                            # call_idが未設定の場合は正式なcall_idを生成
                                            if not self.gateway.call_id:
                                                if self.gateway.client_id:
                                                    self.gateway.call_id = (
                                                        self.gateway.console_bridge.issue_call_id(
                                                            self.gateway.client_id
                                                        )
                                                    )
                                                    self.logger.info(
                                                        "HANDOFF_FAIL_TTS: generated call_id=%s",
                                                        self.gateway.call_id,
                                                    )
                                                    # AICoreにcall_idを設定
                                                    if self.gateway.call_id:
                                                        self.gateway.ai_core.set_call_id(
                                                            self.gateway.call_id
                                                        )
                                                else:
                                                    self.logger.debug(
                                                        "HANDOFF_FAIL_TTS_SKIP: call not started yet "
                                                        "(call_id=%s, no client_id)",
                                                        call_id,
                                                    )
                                                    processed_lines.add(line_hash)
                                                    continue

                                            self.logger.info(
                                                "HANDOFF_FAIL_TTS_DETECTED: call_id=%s text=%r",
                                                call_id,
                                                text,
                                            )

                                            # TTSアナウンスを送信
                                            self.gateway._send_tts(call_id, text, None, False)

                                            # 処理済みとして記録
                                            processed_lines.add(line_hash)

                                    except Exception as e:
                                        self.logger.exception(
                                            "Failed to parse HANDOFF_FAIL_TTS_REQUEST: %s",
                                            e,
                                        )
                                        processed_lines.add(line_hash)

                            # 現在の位置を記録
                            last_position = f.tell()

                            # 処理済みセットが大きくなりすぎないように定期的にクリーンアップ
                            if len(processed_lines) > 1000:
                                processed_lines.clear()
                    except Exception as e:
                        self.logger.exception("Error reading log file: %s", e)

                await asyncio.sleep(0.1)

            except Exception as e:
                self.logger.exception("Error in log monitor loop: %s", e)

    async def _ws_client_loop(self):
        await self.ws_handler.ws_client_loop()

    async def _ws_server_loop(self):
        await self.ws_handler.ws_server_loop()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await self.socket_server.handle_client(reader, writer)

    async def _event_socket_server_loop(self) -> None:
        await self.socket_server.event_socket_server_loop()
