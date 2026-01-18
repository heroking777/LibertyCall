"""Log monitoring loop for network manager."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.common.network_manager import GatewayNetworkManager


class NetworkLogMonitor:
    def __init__(self, manager: "GatewayNetworkManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    async def log_monitor_loop(self) -> None:
        """
        ログファイルを監視し、HANDOFF_FAIL_TTS_REQUESTメッセージを検出してTTSアナウンスを送信
        """
        gateway = self.manager.gateway
        self.logger.debug("Log monitor loop started.")
        log_file = Path("/opt/libertycall/logs/realtime_gateway.log")
        processed_lines = set()  # 処理済みの行を記録（重複防止）

        # ログファイルが存在しない場合は作成を待つ
        if not log_file.exists():
            self.logger.warning("Gateway log file not found, waiting for creation...")
            while not log_file.exists() and gateway.running:
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

        while gateway.running:
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
                                        # 正規表現でcall_idとtextを抽出
                                        import re

                                        call_id_match = re.search(r"call_id=([^\s]+)", line)
                                        text_match = re.search(r"text=(.+?) audio_len=", line)

                                        if call_id_match and text_match:
                                            call_id = call_id_match.group(1)
                                            text = text_match.group(1)

                                            # call_idが"TEMP_CALL"の場合は実際のcall_idを使用
                                            if call_id == "TEMP_CALL":
                                                # gateway.call_idが存在する場合はそれを使用
                                                if gateway.call_id:
                                                    self.logger.info(
                                                        "HANDOFF_FAIL_TTS: TEMP_CALL -> actual call_id=%s",
                                                        gateway.call_id,
                                                    )
                                                    call_id = gateway.call_id
                                                # call_idが存在しない場合はスキップ
                                                elif gateway.client_id:
                                                    # TEMP_CALLでcall_idが未設定の場合は、新しいcall_idを生成
                                                    self.logger.info(
                                                        "HANDOFF_FAIL_TTS: TEMP_CALL with no call_id, generating new call_id",
                                                    )
                                                    gateway.call_id = gateway.console_bridge.issue_call_id(
                                                        gateway.client_id
                                                    )
                                                    call_id = gateway.call_id
                                                    self.logger.info(
                                                        "HANDOFF_FAIL_TTS: Generated call_id=%s for TEMP_CALL",
                                                        call_id,
                                                    )
                                                    # AICoreにcall_idを設定
                                                    if gateway.call_id:
                                                        gateway.ai_core.set_call_id(
                                                            gateway.call_id
                                                        )
                                                else:
                                                    self.logger.debug(
                                                        "HANDOFF_FAIL_TTS_SKIP: call not started yet (call_id=%s, no client_id)",
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
                                            gateway._send_tts(call_id, text, None, False)

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
