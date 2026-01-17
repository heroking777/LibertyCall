#!/usr/bin/env python3
"""Monitoring logic for RTP and background loops."""
import asyncio
import socket
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional


class FreeswitchRTPMonitor:
    """FreeSWITCHの送信RTPポートを監視してASR処理に流し込む（Pull型、pcap方式）"""

    def __init__(
        self,
        gateway: "RealtimeGateway",
        rtp_protocol_cls,
        scapy_available: bool,
        sniff_func=None,
        ip_cls=None,
        udp_cls=None,
        esl_receiver_cls=None,
    ):
        self.gateway = gateway
        self.logger = gateway.logger
        self.freeswitch_rtp_port: Optional[int] = None
        self.monitor_sock: Optional[socket.socket] = None
        self.monitor_transport = None
        self.asr_active = False  # 002.wav再生完了後にTrueになる
        self.capture_thread: Optional[threading.Thread] = None
        self.capture_running = False
        self.active_receivers = {}  # ESL receivers
        self.rtp_protocol_cls = rtp_protocol_cls
        self.scapy_available = scapy_available
        self.sniff_func = sniff_func
        self.ip_cls = ip_cls
        self.udp_cls = udp_cls
        self.esl_receiver_cls = esl_receiver_cls

    def get_rtp_port_from_freeswitch(self) -> Optional[int]:
        """FreeSWITCHから現在の送信RTPポートを取得（RTP情報ファイル優先、uuid_dumpはフォールバック）"""
        return self.gateway.network_manager.get_rtp_port_from_freeswitch()

    def update_uuid_mapping_for_call(self, call_id: str) -> Optional[str]:
        """
        call_idに対応するFreeSWITCH UUIDを取得してマッピングを更新

        :param call_id: 通話ID
        :return: 取得したUUID（失敗時はNone）
        """
        return self.gateway.session_handler.update_uuid_mapping_for_call(call_id)

    async def start_monitoring(self):
        """ESL方式で音声監視を開始"""
        uuid = getattr(self.gateway, "uuid", None)
        if not uuid:
            self.logger.error("[ESL_MONITOR] UUID not found in gateway")
            return

        call_id = f"in-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-4]}"
        self.logger.info(
            "[ESL_MONITOR] Starting ESL audio monitoring for call_id=%s, uuid=%s",
            call_id,
            uuid,
        )

        if not self.esl_receiver_cls:
            raise RuntimeError("ESLAudioReceiver class not provided")
        esl_receiver = self.esl_receiver_cls(call_id, uuid, self.gateway, self.logger)
        esl_receiver.start()

        self.active_receivers[call_id] = esl_receiver

        if hasattr(self.gateway, "call_uuid_map"):
            self.gateway.call_uuid_map[call_id] = uuid

        self.logger.info("[ESL_MONITOR] ESL monitoring started for call_id=%s", call_id)

    async def _check_asr_enable_flag(self):
        """002.wav完了フラグファイルを監視してASRを有効化"""
        check_count = 0
        while self.gateway.running:
            try:
                check_count += 1
                # UUIDベースのフラグファイルを検索（複数の通話に対応）
                flag_files = list(Path("/tmp").glob("asr_enable_*.flag"))

                # デバッグログ（20回に1回、またはフラグファイルが見つかった時）
                if check_count % 20 == 0 or flag_files:
                    self.logger.debug(
                        "[FS_RTP_MONITOR] Checking ASR enable flag (check #%s, found %s flag file(s), asr_active=%s)",
                        check_count,
                        len(flag_files),
                        self.asr_active,
                    )

                if flag_files:
                    # 最初に見つかったフラグファイルでASRを有効化（必ずSAFE_DELAY経由）
                    flag_file = flag_files[0]
                    if not self.asr_active:
                        self.logger.info(
                            "[SAFE_DELAY] 初回アナウンス完了検知、ASR起動を3秒遅延させます"
                        )
                        self._schedule_asr_enable_after_initial_sequence()
                    # フラグファイルは処理済みとして削除（有効化済みでも削除）
                    try:
                        flag_file.unlink()
                        self.logger.info(
                            "[FS_RTP_MONITOR] Removed ASR enable flag: %s", flag_file
                        )
                    except Exception as e:
                        self.logger.warning(
                            "[FS_RTP_MONITOR] Failed to remove flag file: %s", e
                        )
            except Exception as e:
                self.logger.error(
                    "[FS_RTP_MONITOR] Error checking ASR enable flag: %s",
                    e,
                    exc_info=True,
                )

            await asyncio.sleep(0.5)  # 0.5秒間隔でチェック

    async def _monitor_rtp_info_files(self):
        """RTP情報ファイルを定期的に監視して、RTPポートが検出されたら監視を開始"""
        while self.gateway.running:
            try:
                # 既にRTPポートが検出されている場合は監視を開始済み
                if self.freeswitch_rtp_port and self.monitor_sock:
                    await asyncio.sleep(5.0)  # 既に監視中なら5秒間隔でチェック
                    continue

                # RTP情報ファイルをチェック
                rtp_info_files = list(Path("/tmp").glob("rtp_info_*.txt"))
                if rtp_info_files:
                    # 複数ファイルを走査して最も新しい local= 情報を採用する
                    candidate_port = None
                    candidate_mtime = 0.0
                    for filepath in rtp_info_files:
                        try:
                            mtime = filepath.stat().st_mtime
                            with open(filepath, "r") as f:
                                for line in f:
                                    if line.startswith("local="):
                                        local_rtp = line.split("=", 1)[1].strip()
                                        if ":" in local_rtp:
                                            try:
                                                port_str = local_rtp.split(":")[-1]
                                                port = int(port_str)
                                            except ValueError:
                                                continue
                                            if mtime >= candidate_mtime:
                                                candidate_mtime = mtime
                                                candidate_port = port
                        except Exception as e:
                            self.logger.debug(
                                "[FS_RTP_MONITOR] Error reading RTP info file %s: %s",
                                filepath,
                                e,
                            )

                    port = candidate_port
                    if not port:
                        await asyncio.sleep(2.0)
                        continue

                    if port and port != self.freeswitch_rtp_port:
                        self.logger.info(
                            "[FS_RTP_MONITOR] Found RTP port %s from RTP info files, starting monitoring...",
                            port,
                        )
                        self.freeswitch_rtp_port = port
                        # RTPポートで監視を開始（pcap方式）
                        try:
                            if self.scapy_available and self.sniff_func:
                                self.capture_running = True
                                self.capture_thread = threading.Thread(
                                    target=self._pcap_capture_loop,
                                    args=(self.freeswitch_rtp_port,),
                                    daemon=True,
                                )
                                self.capture_thread.start()
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Started pcap monitoring for FreeSWITCH RTP port %s (from RTP info file)",
                                    self.freeswitch_rtp_port,
                                )
                            else:
                                # フォールバック: UDPソケット方式
                                loop = asyncio.get_running_loop()
                                self.monitor_sock = socket.socket(
                                    socket.AF_INET, socket.SOCK_DGRAM
                                )
                                self.monitor_sock.setsockopt(
                                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
                                )
                                self.monitor_sock.setsockopt(
                                    socket.SOL_SOCKET, socket.SO_REUSEPORT, 1
                                )
                                self.monitor_sock.bind(
                                    ("0.0.0.0", self.freeswitch_rtp_port)
                                )
                                self.monitor_sock.setblocking(False)

                                self.monitor_transport, _ = (
                                    await loop.create_datagram_endpoint(
                                        lambda: self.rtp_protocol_cls(self.gateway),
                                        sock=self.monitor_sock,
                                    )
                                )
                                self.logger.info(
                                    "[FS_RTP_MONITOR] Started UDP socket monitoring for FreeSWITCH RTP port %s (from RTP info file)",
                                    self.freeswitch_rtp_port,
                                )
                        except Exception as e:
                            self.logger.error(
                                "[FS_RTP_MONITOR] Failed to start monitoring port %s: %s",
                                port,
                                e,
                                exc_info=True,
                            )
                            self.freeswitch_rtp_port = None

                await asyncio.sleep(2.0)  # 2秒間隔でチェック
            except Exception as e:
                self.logger.error(
                    "[FS_RTP_MONITOR] Error in _monitor_rtp_info_files: %s",
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(2.0)

    def enable_asr(self):
        """002.wav再生完了後にASRを有効化"""
        if not self.asr_active:
            self.asr_active = True
            self.logger.info(
                "[FS_RTP_MONITOR] ASR enabled after 002.wav playback completion"
            )

            # 【修正】AICore.enable_asr()を呼び出してストリームワーカーを起動
            if (
                self.gateway
                and hasattr(self.gateway, "ai_core")
                and self.gateway.ai_core
            ):
                # call_idを取得
                call_id = getattr(self.gateway, "call_id", None)
                # 追加: 現在のマッピング状況をログ出力
                try:
                    current_map = getattr(self.gateway, "call_uuid_map", {})
                except Exception:
                    current_map = {}
                self.logger.warning(
                    "[DEBUG_ENABLE_ASR_ENTRY] call_id=%s call_uuid_map=%s",
                    call_id,
                    current_map,
                )

                if not call_id and hasattr(self.gateway, "_get_effective_call_id"):
                    call_id = self.gateway._get_effective_call_id()
                    self.logger.warning(
                        "[DEBUG_ENABLE_ASR_EFFECTIVE] effective_call_id=%s", call_id
                    )

                if not call_id:
                    self.logger.error(
                        "[ENABLE_ASR_FAILED] Cannot enable ASR: call_id is None. "
                        "This indicates RTP monitoring has not started yet."
                    )
                    return

                # UUIDを取得（call_uuid_mapから、またはupdate_uuid_mapping_for_callで取得）
                uuid = None
                if call_id and hasattr(self.gateway, "call_uuid_map"):
                    uuid = self.gateway.call_uuid_map.get(call_id)

                # UUIDが見つからない場合は、update_uuid_mapping_for_callで取得を試みる
                if call_id and not uuid:
                    self.logger.warning(
                        "[ENABLE_ASR_UUID_MISSING] call_id=%s not in map, attempting update_uuid_mapping",
                        call_id,
                    )
                    uuid = self.update_uuid_mapping_for_call(call_id)

                # client_idを取得
                client_id = getattr(self.gateway, "client_id", "000") or "000"

                # 追加: uuid取得結果のログ
                self.logger.warning(
                    "[DEBUG_ENABLE_ASR_UUID] call_id=%s uuid=%s", call_id, uuid
                )

                if not uuid:
                    self.logger.error(
                        "[ENABLE_ASR_FAILED] Cannot enable ASR: uuid not found for call_id=%s. RTP info file may not exist yet.",
                        call_id,
                    )
                    return

                try:
                    self.gateway.ai_core.enable_asr(uuid, client_id=client_id)
                    self.logger.info(
                        "[ENABLE_ASR_SUCCESS] ASR enabled: uuid=%s call_id=%s client_id=%s",
                        uuid,
                        call_id,
                        client_id,
                    )
                except Exception as e:
                    self.logger.error(
                        "[FS_RTP_MONITOR] Failed to call AICore.enable_asr(): %s",
                        e,
                        exc_info=True,
                    )

            else:
                self.logger.warning(
                    "[FS_RTP_MONITOR] Cannot call AICore.enable_asr(): gateway or ai_core not available"
                )

    def _schedule_asr_enable_after_initial_sequence(
        self, base_delay: float = 3.0, max_wait: float = 10.0
    ):
        """
        初回アナウンス完了を待ってからASRを有効化する
        - base_delay: 完了確認後にさらに待つ秒数（デフォルト3秒）
        - max_wait: 初回アナウンス完了待ちの上限秒数
        """
        # すでにASRが有効なら何もしない
        if self.asr_active:
            return

        # 既存のタイマーをキャンセル（多重スケジュール防止）
        gateway_timer = getattr(self.gateway, "_asr_enable_timer", None)
        if gateway_timer:
            try:
                gateway_timer.cancel()
            except Exception:
                pass

        def _runner():
            waited = 0.0
            initial_done = getattr(self.gateway, "initial_sequence_completed", False)
            if not initial_done:
                self.logger.info(
                    "[SAFE_DELAY] 初回アナウンス完了待ちでASR起動を遅延 (max_wait=%ss, base_delay=%ss)",
                    max_wait,
                    base_delay,
                )
            # 初回アナウンス完了を待つ（最大 max_wait 秒）
            while (
                not getattr(self.gateway, "initial_sequence_completed", False)
                and waited < max_wait
            ):
                time.sleep(0.5)
                waited += 0.5
            if base_delay > 0:
                time.sleep(base_delay)
                waited += base_delay
            try:
                self.enable_asr()
                self.logger.info(
                    "[SAFE_DELAY] ASR enabled (waited=%.1fs, initial_sequence_completed=%s)",
                    waited,
                    getattr(self.gateway, "initial_sequence_completed", False),
                )
            except Exception as e:
                self.logger.error(
                    "[SAFE_DELAY] Failed to enable ASR: %s", e, exc_info=True
                )

        timer = threading.Timer(0.0, _runner)
        timer.daemon = True
        timer.start()
        self.gateway._asr_enable_timer = timer

    def _pcap_capture_loop(self, port: int):
        """pcap方式でRTPパケットをキャプチャするループ（別スレッドで実行）"""
        # 【最優先デバッグ】関数の最初で即座に出力
        print(f"DEBUG_TRACE: _pcap_capture_loop ENTERED port={port}", flush=True)
        try:
            self.logger.info("[FS_RTP_MONITOR] Starting pcap capture for port %s", port)
            # scapyのsniff()を使用してパケットをキャプチャ
            # filter: UDPパケットで、指定ポートを使用
            # store=False: パケットをメモリに保存しない（パフォーマンス向上）
            # prn: パケットを受信したときに呼び出すコールバック関数
            # 【修正】宛先ポート（dst port）のみを指定し、送信パケット（システム音声）を除外する
            filter_str = f"udp dst port {port}"
            try:
                self.logger.info(
                    "[PCAP_CONFIG] Starting capture with filter: '%s'", filter_str
                )
            except Exception:
                pass
            # 【強制出力】標準出力に出して即時確認（loggerに依存しない）
            try:
                print(
                    f"DEBUG_PRINT: Starting pcap with filter='{filter_str}'",
                    flush=True,
                )
            except Exception:
                pass
            if not self.sniff_func:
                raise RuntimeError("scapy sniff is not available")
            self.sniff_func(
                filter=filter_str,
                prn=self._process_captured_packet,
                stop_filter=lambda x: not self.capture_running,
                store=False,
            )
        except Exception as e:
            self.logger.error(
                "[FS_RTP_MONITOR] Error in pcap capture loop: %s", e, exc_info=True
            )
        finally:
            self.logger.info(
                "[FS_RTP_MONITOR] pcap capture loop ended for port %s", port
            )

    def _process_captured_packet(self, packet):
        """キャプチャしたパケットを処理"""
        # 【デバッグ】パケット受信時に即座に出力（50回に1回）
        if not hasattr(self, "_packet_debug_count"):
            self._packet_debug_count = 0
        self._packet_debug_count += 1
        if self._packet_debug_count % 50 == 1:
            print(
                f"DEBUG_TRACE: _process_captured_packet called count={self._packet_debug_count}",
                flush=True,
            )
        try:
            # IP層とUDP層を確認
            if not self.ip_cls or not self.udp_cls:
                raise RuntimeError("scapy IP/UDP layers are not available")
            if self.ip_cls in packet and self.udp_cls in packet:
                ip_layer = packet[self.ip_cls]
                udp_layer = packet[self.udp_cls]

                # 送信元と宛先の情報を取得
                src_ip = ip_layer.src
                dst_ip = ip_layer.dst
                src_port = udp_layer.sport
                dst_port = udp_layer.dport

                # UDPペイロード（RTPデータ）を取得
                rtp_data = bytes(udp_layer.payload)

                if len(rtp_data) > 0:
                    # 送信元アドレスとして使用（リモートからFreeSWITCHへのパケットをキャプチャ）
                    addr = (src_ip, src_port)

                    # ログ出力
                    self.logger.debug(
                        "[RTP_RECV] Captured %s bytes from %s (pcap)",
                        len(rtp_data),
                        addr,
                    )
                    self.logger.info(
                        "[RTP_RECV_RAW] from=%s, len=%s (pcap)",
                        addr,
                        len(rtp_data),
                    )

                    # デバッグ: RTPペイロード（音声データ）のサイズを確認
                    if len(rtp_data) > 12:
                        audio_payload_size = len(rtp_data) - 12  # RTPヘッダー12バイトを除く
                        self.logger.debug(
                            "[RTP_AUDIO] RTP packet: total=%s bytes, header=12 bytes, audio_payload=%s bytes (pcap)",
                            len(rtp_data),
                            audio_payload_size,
                        )

                    # asyncioイベントループでhandle_rtp_packetを実行
                    # 別スレッドからasyncioを呼び出すため、新しいイベントループを作成
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.gateway.handle_rtp_packet(rtp_data, addr)
                        )
                        loop.close()
                    except Exception as e:
                        self.logger.error(
                            "[FS_RTP_MONITOR] Error processing captured packet: %s",
                            e,
                            exc_info=True,
                        )
        except Exception as e:
            self.logger.error(
                "[FS_RTP_MONITOR] Error in _process_captured_packet: %s",
                e,
                exc_info=True,
            )

    async def stop_monitoring(self):
        """監視を停止"""
        self.capture_running = False
        if self.capture_thread and self.capture_thread.is_alive():
            # スレッドの終了を待つ（最大5秒）
            self.capture_thread.join(timeout=5.0)
        if self.monitor_transport:
            self.monitor_transport.close()
        if self.monitor_sock:
            self.monitor_sock.close()
        self.logger.info("[FS_RTP_MONITOR] Stopped monitoring FreeSWITCH RTP port")


class ESLAudioReceiver:
    """FreeSWITCH ESL経由の音声受信。"""

    def __init__(self, call_id, uuid, gateway, logger):
        self.call_id = call_id
        self.uuid = uuid
        self.gateway = gateway
        self.logger = logger
        self.running = False
        self.thread = None
        self.conn = None

    def start(self):
        """ESL接続と音声受信を開始。"""
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        self.logger.info(
            "[ESL_AUDIO] Started for call_id=%s, uuid=%s", self.call_id, self.uuid
        )

    def _receive_loop(self):
        """ESLイベントを受信してRTPに流す。"""
        try:
            from libs.esl.ESL import ESLconnection

            self.conn = ESLconnection("127.0.0.1", "8021", "ClueCon")

            if not self.conn.connected():
                self.logger.error("[ESL_AUDIO] Failed to connect to FreeSWITCH ESL")
                return

            self.conn.events("plain", "CHANNEL_AUDIO")
            self.conn.filter("Unique-ID", self.uuid)

            self.logger.info(
                "[ESL_AUDIO] Connected and subscribed to UUID=%s", self.uuid
            )

            while self.running:
                event = self.conn.recvEventTimed(100)

                if not event:
                    continue

                if event.getHeader("Event-Name") == "CHANNEL_AUDIO":
                    audio_data = event.getBody()
                    if audio_data:
                        self.gateway.handle_rtp_packet(self.call_id, audio_data)

        except Exception as e:
            self.logger.error("[ESL_AUDIO] Exception: %s", e)
            traceback.print_exc()

    def stop(self):
        """ESL受信を停止。"""
        self.running = False
        if self.conn:
            self.conn.disconnect()
        self.logger.info("[ESL_AUDIO] Stopped for call_id=%s", self.call_id)


class GatewayMonitorManager:
    def __init__(
        self,
        gateway: "RealtimeGateway",
        rtp_protocol_cls,
        scapy_available: bool,
        sniff_func=None,
        ip_cls=None,
        udp_cls=None,
        esl_receiver_cls=None,
    ):
        self.gateway = gateway
        self.logger = gateway.logger
        self.fs_rtp_monitor = FreeswitchRTPMonitor(
            gateway,
            rtp_protocol_cls,
            scapy_available,
            sniff_func=sniff_func,
            ip_cls=ip_cls,
            udp_cls=udp_cls,
            esl_receiver_cls=esl_receiver_cls,
        )

    def start_no_input_monitoring(self) -> None:
        if not getattr(self.gateway, "_silence_loop_started", False):
            self.logger.info("RealtimeGateway started — scheduling silence monitor loop")
            try:
                # イベントループが確実に起動していることを確認
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._no_input_monitor_loop())
                self.gateway._silence_loop_started = True
                self.logger.info(
                    "NO_INPUT_MONITOR_LOOP: scheduled successfully (task=%r)",
                    task,
                )
            except RuntimeError as e:
                # イベントループがまだ起動していない場合（通常は発生しない）
                self.logger.error(
                    "Event loop not running yet — cannot start silence monitor loop: %s",
                    e,
                )

                async def delayed_start():
                    await asyncio.sleep(1.0)
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(self._no_input_monitor_loop())
                        self.gateway._silence_loop_started = True
                        self.logger.info(
                            "NO_INPUT_MONITOR_LOOP: scheduled successfully after delay (task=%r)",
                            task,
                        )
                    except Exception as ex:
                        self.logger.exception(
                            "Delayed silence monitor launch failed: %s", ex
                        )

                asyncio.create_task(delayed_start())
                self.logger.warning(
                    "Event loop not running yet — scheduled delayed silence monitor launch"
                )
        else:
            self.logger.warning(
                "Silence monitor loop already started, skipping duplicate launch"
            )

    def start_rtp_monitoring(self) -> None:
        if self.fs_rtp_monitor:
            asyncio.create_task(self.fs_rtp_monitor.start_monitoring())

            # ★ 一時テスト: 通話開始から8秒後にASRを強制有効化（デバッグ用）
            # TODO: 動作確認後、この行を削除してgateway_event_listener.py連携に切り替える
            async def force_enable_asr_after_delay():
                await asyncio.sleep(8.0)
                if not self.fs_rtp_monitor.asr_active:
                    self.logger.info(
                        "[FS_RTP_MONITOR] DEBUG: Force-enabling ASR after 8 seconds (temporary test)"
                    )
                    self.fs_rtp_monitor._schedule_asr_enable_after_initial_sequence()

            asyncio.create_task(force_enable_asr_after_delay())

    async def _no_input_monitor_loop(self):
        """無音状態を監視し、自動ハングアップを行う"""
        self.logger.info("NO_INPUT_MONITOR_LOOP: started")

        while self.gateway.running:
            try:
                now = time.monotonic()

                # _active_calls が存在しない場合は初期化
                if not hasattr(self.gateway, "_active_calls"):
                    self.gateway._active_calls = set()

                # 現在アクティブな通話を走査
                active_call_ids = (
                    list(self.gateway._active_calls)
                    if self.gateway._active_calls
                    else []
                )

                # アクティブな通話がない場合は待機
                if not active_call_ids:
                    await asyncio.sleep(1.0)
                    continue

                # 各アクティブな通話について無音検出を実行
                for call_id in active_call_ids:
                    try:
                        # 最後に有音を検出した時刻を取得
                        last_voice = self.gateway._last_voice_time.get(call_id, 0)

                        # 最後に有音を検出した時刻が0の場合は、TTS送信完了時刻を使用
                        if last_voice == 0:
                            last_voice = self.gateway._last_tts_end_time.get(call_id, now)

                        # 無音継続時間を計算
                        elapsed = now - last_voice

                        # TTS送信中は無音検出をスキップ
                        if self.gateway.is_speaking_tts:
                            continue

                        # 初回シーケンス再生中は無音検出をスキップ
                        if self.gateway.initial_sequence_playing:
                            continue

                        # 無音5秒ごとに警告ログ出力
                        if elapsed > 5 and abs(elapsed % 5) < 1:
                            self.logger.warning(
                                "[SILENCE DETECTED] %.1fs of silence call_id=%s",
                                elapsed,
                                call_id,
                            )

                        # 警告送信済みセットを初期化（存在しない場合）
                        if call_id not in self.gateway._silence_warning_sent:
                            self.gateway._silence_warning_sent[call_id] = set()

                        warnings = self.gateway._silence_warning_sent[call_id]

                        # 段階的な無音警告（5秒、15秒、25秒）とアナウンス再生
                        if elapsed >= 5.0 and 5.0 not in warnings:
                            warnings.add(5.0)
                            self.logger.warning(
                                "[SILENCE DETECTED] %.1fs of silence for call_id=%s",
                                elapsed,
                                call_id,
                            )
                            await self.gateway._play_silence_warning(call_id, 5.0)
                        elif elapsed >= 15.0 and 15.0 not in warnings:
                            warnings.add(15.0)
                            self.logger.warning(
                                "[SILENCE DETECTED] %.1fs of silence for call_id=%s",
                                elapsed,
                                call_id,
                            )
                            await self.gateway._play_silence_warning(call_id, 15.0)
                        elif elapsed >= 25.0 and 25.0 not in warnings:
                            warnings.add(25.0)
                            self.logger.warning(
                                "[SILENCE DETECTED] %.1fs of silence for call_id=%s",
                                elapsed,
                                call_id,
                            )
                            await self.gateway._play_silence_warning(call_id, 25.0)

                        # 無音が規定時間を超えたら強制切断
                        max_silence_time = getattr(
                            self.gateway, "SILENCE_HANGUP_TIME", 20.0
                        )
                        if elapsed > max_silence_time:
                            self.logger.warning(
                                "[AUTO-HANGUP] Silence limit exceeded (%.1fs) call_id=%s",
                                elapsed,
                                call_id,
                            )

                            # console_bridge に無音切断イベントを記録
                            # 注意: enabled チェックは record_event() 内で行わない（ファイル記録のため常に実行）
                            try:
                                caller_number = (
                                    getattr(self.gateway.ai_core, "caller_number", None)
                                    or "unknown"
                                )
                                self.gateway.console_bridge.record_event(
                                    call_id,
                                    "auto_hangup_silence",
                                    {
                                        "elapsed": elapsed,
                                        "caller": caller_number,
                                        "max_silence_time": max_silence_time,
                                    },
                                )
                                self.logger.info(
                                    "[AUTO-HANGUP] Event recorded: call_id=%s elapsed=%.1fs",
                                    call_id,
                                    elapsed,
                                )
                            except Exception as e:
                                self.logger.error(
                                    "[AUTO-HANGUP] Failed to record event for call_id=%s: %s",
                                    call_id,
                                    e,
                                    exc_info=True,
                                )

                            try:
                                # 非同期タスクとして実行（既存の同期関数を呼び出す）
                                loop = asyncio.get_running_loop()
                                loop.run_in_executor(
                                    None, self.gateway._handle_hangup, call_id
                                )
                            except Exception as e:
                                self.logger.exception(
                                    "[AUTO-HANGUP] Hangup failed call_id=%s error=%s",
                                    call_id,
                                    e,
                                )
                            # 警告セットをクリア（次の通話のために）
                            self.gateway._silence_warning_sent.pop(call_id, None)
                            continue

                        # 音声が検出された場合は警告セットをリセット
                        if elapsed < 1.0:  # 1秒以内に音声が検出された場合
                            if call_id in self.gateway._silence_warning_sent:
                                self.gateway._silence_warning_sent[call_id].clear()
                    except Exception as e:
                        self.logger.exception(
                            "NO_INPUT_MONITOR_LOOP error for call_id=%s: %s",
                            call_id,
                            e,
                        )

            except Exception as e:
                self.logger.exception("NO_INPUT_MONITOR_LOOP error: %s", e)

            await asyncio.sleep(1.0)  # 1秒間隔でチェック
