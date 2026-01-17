#!/usr/bin/env python3
"""Network/server handling for realtime gateway."""
import asyncio
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import websockets

from libertycall.client_loader import load_client_profile


class GatewayNetworkManager:
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        self.logger = gateway.logger

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
        """イベントソケットファイルの事前クリーンアップ。"""
        if self.gateway.event_socket_path.exists():
            try:
                self.gateway.event_socket_path.unlink()
                self.logger.info(
                    "[EVENT_SOCKET] Removed existing socket file: %s",
                    self.gateway.event_socket_path,
                )
            except Exception as e:
                self.logger.warning(
                    "[EVENT_SOCKET] Failed to remove existing socket: %s", e
                )

    def _cleanup_sockets(self) -> None:
        """イベントソケットファイルの後処理。"""
        if self.gateway.event_socket_path.exists():
            try:
                self.gateway.event_socket_path.unlink()
                self.logger.info(
                    "[EVENT_SOCKET] Removed socket file: %s",
                    self.gateway.event_socket_path,
                )
            except Exception as e:
                self.logger.warning(
                    "[EVENT_SOCKET] Failed to remove socket file: %s", e
                )

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
        gateway = self.gateway
        while gateway.running:
            try:
                async with websockets.connect(gateway.ws_url) as websocket:
                    gateway.websocket = websocket
                    self.logger.info("WebSocket connected (Control Plane)")
                    async for message in websocket:
                        if isinstance(message, str):
                            try:
                                data = json.loads(message)
                                msg_type = data.get("type")

                                # ▼▼▼ クライアント初期化ロジック ▼▼▼
                                if msg_type == "init":
                                    try:
                                        req_client_id = data.get("client_id")
                                        req_call_id = data.get("call_id")
                                        req_caller_number = data.get(
                                            "caller_number"
                                        )  # caller_numberを取得
                                        self.logger.debug(
                                            "[Init] Request for client_id: %s",
                                            req_client_id,
                                        )

                                        # プロファイル読み込み
                                        gateway.client_profile = load_client_profile(
                                            req_client_id
                                        )

                                        # メモリ展開
                                        if gateway.call_id and (
                                            gateway.client_id != req_client_id
                                            or (
                                                req_call_id
                                                and gateway.call_id != req_call_id
                                            )
                                        ):
                                            gateway._complete_console_call()
                                        gateway._reset_call_state()
                                        gateway.client_id = req_client_id
                                        gateway.config = gateway.client_profile["config"]
                                        gateway.rules = gateway.client_profile["rules"]

                                        # クライアントIDが変更された場合、AICoreの会話フローを再読み込み
                                        if hasattr(gateway.ai_core, "set_client_id"):
                                            gateway.ai_core.set_client_id(req_client_id)
                                        elif hasattr(gateway.ai_core, "client_id"):
                                            gateway.ai_core.client_id = req_client_id
                                            if hasattr(gateway.ai_core, "reload_flow"):
                                                gateway.ai_core.reload_flow()

                                        # caller_numberをAICoreに設定
                                        if req_caller_number:
                                            gateway.ai_core.caller_number = req_caller_number
                                            self.logger.debug(
                                                "[Init] Set caller_number: %s",
                                                req_caller_number,
                                            )
                                        else:
                                            # caller_numberが送られてこない場合はNone（後で"-"として記録される）
                                            gateway.ai_core.caller_number = None
                                            self.logger.debug(
                                                "[Init] caller_number not provided in init message"
                                            )

                                        gateway._ensure_console_session(
                                            call_id_override=req_call_id
                                        )
                                        # 非同期タスクとして実行（結果を待たない）
                                        task = asyncio.create_task(
                                            gateway._queue_initial_audio_sequence(
                                                gateway.client_id
                                            )
                                        )

                                        def _log_init_task_result(t):
                                            try:
                                                t.result()  # 例外があればここで再送出される
                                            except Exception as e:
                                                import traceback

                                                self.logger.error(
                                                    "[INIT_TASK_ERR] Initial sequence task failed: %s\n%s",
                                                    e,
                                                    traceback.format_exc(),
                                                )

                                        task.add_done_callback(_log_init_task_result)
                                        self.logger.warning(
                                            "[INIT_TASK_START] Created task for %s",
                                            gateway.client_id,
                                        )

                                        self.logger.debug(
                                            "[Init] Loaded: %s",
                                            gateway.config.get("client_name"),
                                        )
                                    except Exception as e:
                                        self.logger.debug("[Init Error] %s", e)
                                    continue
                                if msg_type == "call_end":
                                    try:
                                        req_call_id = data.get("call_id")
                                        if req_call_id and gateway.call_id == req_call_id:
                                            gateway._stop_recording()
                                            gateway._complete_console_call()
                                    except Exception as e:
                                        self.logger.error(
                                            "call_end handling failed: %s", e
                                        )
                                    continue
                                # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

                            except json.JSONDecodeError:
                                pass
            except Exception:
                await asyncio.sleep(gateway.reconnect_delay)
            finally:
                gateway.websocket = None

    async def _ws_server_loop(self):
        """WebSocketサーバーとしてAsterisk側からの接続を受け付ける"""
        gateway = self.gateway
        ws_server_port = 9001
        ws_server_host = "0.0.0.0"

        # WebSocket起動前にポートを確認・解放
        self.logger.debug(
            "[BOOT] Checking WebSocket port %s availability", ws_server_port
        )
        gateway._free_port(ws_server_port)

        async def handle_asterisk_connection(websocket):
            """Asterisk側からのWebSocket接続を処理"""
            self.logger.info(
                "[WS Server] New connection from %s", websocket.remote_address
            )
            try:
                async for message in websocket:
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")

                            if msg_type == "init":
                                self.logger.info(
                                    "[WS Server] INIT from Asterisk: %s", data
                                )
                                # 既存のinit処理ロジックを再利用
                                await gateway._handle_init_from_asterisk(data)
                            else:
                                self.logger.debug(
                                    "[WS Server] Unknown message type: %s", msg_type
                                )
                        except json.JSONDecodeError as e:
                            self.logger.warning(
                                "[WS Server] Invalid JSON: %s", e
                            )
                        except Exception as e:
                            self.logger.error(
                                "[WS Server] Error processing message: %s",
                                e,
                                exc_info=True,
                            )
            except websockets.exceptions.ConnectionClosed:
                self.logger.debug(
                    "[WS Server] Connection closed: %s",
                    websocket.remote_address,
                )
            except Exception as e:
                self.logger.error(
                    "[WS Server] Connection error: %s", e, exc_info=True
                )

        while gateway.running:
            try:
                async with websockets.serve(
                    handle_asterisk_connection, ws_server_host, ws_server_port
                ) as server:
                    self.logger.info(
                        "[WS Server] Listening on ws://%s:%s",
                        ws_server_host,
                        ws_server_port,
                    )
                    # サーバーが実際に起動したことを確認
                    if server:
                        self.logger.info(
                            "[WS Server] Server started successfully, waiting for connections..."
                        )
                    # サーバーを起動し続ける
                    await asyncio.Future()  # 永久に待機
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    self.logger.error(
                        "[WS Server] Port %s still in use after cleanup, retrying in 5s...",
                        ws_server_port,
                    )
                    await asyncio.sleep(5)
                    # 再試行前に再度ポートを解放
                    gateway._free_port(ws_server_port)
                    continue
                else:
                    self.logger.error(
                        "[WS Server] Failed to start: %s", e, exc_info=True
                    )
                    await asyncio.sleep(5)  # エラー時は5秒待って再試行
            except Exception as e:
                self.logger.error(
                    "[WS Server] Failed to start: %s", e, exc_info=True
                )
                await asyncio.sleep(5)  # エラー時は5秒待って再試行

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """クライアント接続ハンドラー"""
        try:
            while self.gateway.running:
                # データを受信（JSON形式）
                data = await reader.read(4096)
                if not data:
                    break

                try:
                    message = json.loads(data.decode("utf-8"))
                    event_type = message.get("event")
                    uuid = message.get("uuid")
                    call_id = message.get("call_id")
                    client_id = message.get("client_id", "000")

                    self.logger.info(
                        "[EVENT_SOCKET] Received event: %s uuid=%s call_id=%s",
                        event_type,
                        uuid,
                        call_id,
                    )

                    if event_type == "call_start":
                        # CHANNEL_ANSWERイベント
                        if call_id:
                            # call_idが指定されている場合はそれを使用
                            effective_call_id = call_id
                        elif uuid:
                            # UUIDからcall_idを生成
                            effective_call_id = self.gateway._generate_call_id_from_uuid(
                                uuid, client_id
                            )
                        else:
                            self.logger.warning(
                                "[EVENT_SOCKET] call_start event missing call_id and uuid"
                            )
                            writer.write(
                                b'{"status": "error", "message": "missing call_id or uuid"}\n'
                            )
                            await writer.drain()
                            continue

                        # UUIDとcall_idのマッピングを保存
                        if uuid and effective_call_id:
                            self.gateway.call_uuid_map[effective_call_id] = uuid
                            self.logger.info(
                                "[EVENT_SOCKET] Mapped call_id=%s -> uuid=%s",
                                effective_call_id,
                                uuid,
                            )

                        # on_call_start()を呼び出す
                        try:
                            if hasattr(self.gateway.ai_core, "on_call_start"):
                                self.gateway.ai_core.on_call_start(
                                    effective_call_id, client_id=client_id
                                )
                                self.logger.info(
                                    "[EVENT_SOCKET] on_call_start() called for call_id=%s client_id=%s",
                                    effective_call_id,
                                    client_id,
                                )
                            else:
                                self.logger.error(
                                    "[EVENT_SOCKET] ai_core.on_call_start() not found"
                                )
                        except Exception as e:
                            self.logger.exception(
                                "[EVENT_SOCKET] Error calling on_call_start(): %s",
                                e,
                            )

                        # RealtimeGateway側の状態を更新
                        self.logger.warning(
                            "[CALL_START_TRACE] [LOC_START] Adding %s to _active_calls (event_socket) at %.3f",
                            effective_call_id,
                            time.time(),
                        )
                        self.gateway._active_calls.add(effective_call_id)
                        self.gateway.call_id = effective_call_id
                        self.gateway.client_id = client_id
                        self.logger.info(
                            "[EVENT_SOCKET] Added call_id=%s to _active_calls, set call_id and client_id=%s",
                            effective_call_id,
                            client_id,
                        )

                        # 初回アナウンス再生処理を実行（非同期タスクとして実行）
                        try:
                            task = asyncio.create_task(
                                self.gateway._queue_initial_audio_sequence(client_id)
                            )

                            def _log_init_task_result(t):
                                try:
                                    t.result()  # 例外があればここで再送出される
                                except Exception as e:
                                    import traceback

                                    self.logger.error(
                                        "[INIT_TASK_ERR] Initial sequence task failed: %s\n%s",
                                        e,
                                        traceback.format_exc(),
                                    )

                            task.add_done_callback(_log_init_task_result)
                            self.logger.warning(
                                "[INIT_TASK_START] Created task for %s",
                                client_id,
                            )
                            self.logger.info(
                                "[EVENT_SOCKET] _queue_initial_audio_sequence() called for call_id=%s client_id=%s",
                                effective_call_id,
                                client_id,
                            )
                        except Exception as e:
                            self.logger.exception(
                                "[EVENT_SOCKET] Error calling _queue_initial_audio_sequence(): %s",
                                e,
                            )

                        writer.write(b'{"status": "ok"}\n')
                        await writer.drain()

                    elif event_type == "call_end":
                        # CHANNEL_HANGUPイベント
                        effective_call_id = None
                        try:
                            if call_id:
                                effective_call_id = call_id
                            elif uuid:
                                # UUIDからcall_idを逆引き
                                for cid, u in self.gateway.call_uuid_map.items():
                                    if u == uuid:
                                        effective_call_id = cid
                                        break

                                if not effective_call_id:
                                    self.logger.warning(
                                        "[EVENT_SOCKET] call_end event: uuid=%s not found in call_uuid_map",
                                        uuid,
                                    )
                                    writer.write(
                                        b'{"status": "error", "message": "uuid not found"}\n'
                                    )
                                    await writer.drain()
                                    continue
                            else:
                                self.logger.warning(
                                    "[EVENT_SOCKET] call_end event missing call_id and uuid"
                                )
                                writer.write(
                                    b'{"status": "error", "message": "missing call_id or uuid"}\n'
                                )
                                await writer.drain()
                                continue

                            # on_call_end()を呼び出す
                            try:
                                if hasattr(self.gateway.ai_core, "on_call_end"):
                                    self.gateway.ai_core.on_call_end(
                                        effective_call_id,
                                        source="gateway_event_listener",
                                    )
                                    self.logger.info(
                                        "[EVENT_SOCKET] on_call_end() called for call_id=%s",
                                        effective_call_id,
                                    )
                                else:
                                    self.logger.error(
                                        "[EVENT_SOCKET] ai_core.on_call_end() not found"
                                    )
                                # 【追加】通話ごとのASRインスタンスをクリーンアップ
                                if hasattr(
                                    self.gateway.ai_core, "cleanup_asr_instance"
                                ):
                                    self.gateway.ai_core.cleanup_asr_instance(
                                        effective_call_id
                                    )
                                    self.logger.info(
                                        "[EVENT_SOCKET] cleanup_asr_instance() called for call_id=%s",
                                        effective_call_id,
                                    )
                            except Exception as e:
                                self.logger.exception(
                                    "[EVENT_SOCKET] Error calling on_call_end(): %s",
                                    e,
                                )

                            if self.gateway.call_id == effective_call_id:
                                self.gateway.call_id = None

                            # UUIDとcall_idのマッピングを削除
                            if effective_call_id in self.gateway.call_uuid_map:
                                del self.gateway.call_uuid_map[effective_call_id]

                            writer.write(b'{"status": "ok"}\n')
                            await writer.drain()
                        except Exception as e:
                            self.logger.error(
                                "[EVENT_SOCKET_ERR] Error during call_end processing for call_id=%s: %s",
                                effective_call_id,
                                e,
                                exc_info=True,
                            )
                        finally:
                            # ★どんなエラーがあっても、ここは必ず実行する★
                            self.logger.warning(
                                "[FINALLY_BLOCK_ENTRY] Entered finally block for call_id=%s",
                                effective_call_id,
                            )
                            if effective_call_id:
                                call_end_time = time.time()
                                # _active_calls から削除
                                self.logger.warning(
                                    "[FINALLY_ACTIVE_CALLS] Before removal: call_id=%s in _active_calls=%s",
                                    effective_call_id,
                                    effective_call_id in self.gateway._active_calls
                                    if hasattr(self.gateway, "_active_calls")
                                    else False,
                                )
                                if (
                                    hasattr(self.gateway, "_active_calls")
                                    and effective_call_id in self.gateway._active_calls
                                ):
                                    self.gateway._active_calls.remove(effective_call_id)
                                    self.logger.warning(
                                        "[EVENT_SOCKET_DONE] Removed %s from active_calls (finally block) at %.3f",
                                        effective_call_id,
                                        call_end_time,
                                    )
                                self.logger.warning(
                                    "[FINALLY_ACTIVE_CALLS_REMOVED] After removal: call_id=%s in _active_calls=%s",
                                    effective_call_id,
                                    effective_call_id in self.gateway._active_calls
                                    if hasattr(self.gateway, "_active_calls")
                                    else False,
                                )

                                # 管理用データのクリーンアップ
                                if effective_call_id in self.gateway._recovery_counts:
                                    del self.gateway._recovery_counts[effective_call_id]
                                if effective_call_id in self.gateway._initial_sequence_played:
                                    self.gateway._initial_sequence_played.discard(
                                        effective_call_id
                                    )
                                if effective_call_id in self.gateway._last_processed_sequence:
                                    del self.gateway._last_processed_sequence[
                                        effective_call_id
                                    ]
                                self.gateway._last_voice_time.pop(effective_call_id, None)
                                self.gateway._last_silence_time.pop(
                                    effective_call_id, None
                                )
                                self.gateway._last_tts_end_time.pop(
                                    effective_call_id, None
                                )
                                self.gateway._last_user_input_time.pop(
                                    effective_call_id, None
                                )
                                self.gateway._silence_warning_sent.pop(
                                    effective_call_id, None
                                )
                                if hasattr(self.gateway, "_initial_tts_sent"):
                                    self.gateway._initial_tts_sent.discard(
                                        effective_call_id
                                    )
                                self.logger.debug(
                                    "[CALL_CLEANUP] Cleared state for call_id=%s",
                                    effective_call_id,
                                )
                    else:
                        self.logger.warning(
                            "[EVENT_SOCKET] Unknown event type: %s", event_type
                        )
                        writer.write(
                            b'{"status": "error", "message": "unknown event type"}\n'
                        )
                        await writer.drain()

                except json.JSONDecodeError as e:
                    self.logger.error("[EVENT_SOCKET] Failed to parse JSON: %s", e)
                    writer.write(b'{"status": "error", "message": "invalid json"}\n')
                    await writer.drain()
                except Exception as e:
                    self.logger.exception("[EVENT_SOCKET] Error handling event: %s", e)
                    writer.write(b'{"status": "error", "message": "internal error"}\n')
                    await writer.drain()

        except Exception as e:
            self.logger.exception("[EVENT_SOCKET] Client handler error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _event_socket_server_loop(self) -> None:
        """
        FreeSWITCHイベント受信用Unixソケットサーバー

        gateway_event_listener.pyからイベントを受信して、
        on_call_start() / on_call_end() を呼び出す
        """
        self._setup_server_socket()
        self.logger.info("[EVENT_SOCKET_DEBUG] _event_socket_server_loop started")

        try:
            self.logger.info("[EVENT_SOCKET_DEBUG] About to start unix server")
            # Unixソケットサーバーを起動
            self.gateway.event_server = await asyncio.start_unix_server(
                self.handle_client,
                str(self.gateway.event_socket_path),
            )
            self.logger.info(
                "[EVENT_SOCKET] Server started on %s",
                self.gateway.event_socket_path,
            )
            # サーバーが停止するまで待機
            async with self.gateway.event_server:
                await self.gateway.event_server.serve_forever()
        except Exception as e:
            self.logger.error("[EVENT_SOCKET] Server error: %s", e, exc_info=True)
        finally:
            # クリーンアップ
            self._cleanup_sockets()
