"""RTP packet builder and protocol helpers."""
from __future__ import annotations

import asyncio
import struct
from typing import Optional, Tuple, TYPE_CHECKING

from libertycall.gateway.core.gateway_utils import IGNORE_RTP_IPS

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.realtime_gateway import RealtimeGateway


class RTPPacketBuilder:
    RTP_VERSION = 2

    def __init__(self, payload_type: int, sample_rate: int, ssrc: Optional[int] = None):
        self.payload_type = payload_type
        self.sample_rate = sample_rate
        self.ssrc = ssrc or self._generate_ssrc()
        self.sequence_number = 0
        self.timestamp = 0

    def _generate_ssrc(self) -> int:
        import random

        return random.randint(0, 0xFFFFFFFF)

    def build_packet(self, payload: bytes) -> bytes:
        header = bytearray(12)
        header[0] = (self.RTP_VERSION << 6)
        header[1] = self.payload_type & 0x7F
        struct.pack_into(">H", header, 2, self.sequence_number)
        struct.pack_into(">I", header, 4, self.timestamp)
        struct.pack_into(">I", header, 8, self.ssrc)
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        samples = len(payload) // 2
        self.timestamp = (self.timestamp + samples) & 0xFFFFFFFF
        return bytes(header) + payload


class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        # 受信元アドレスをロックするためのフィールド（最初のパケット送信元を固定）
        self.remote_addr: Optional[Tuple[str, int]] = None
        # 受信元SSRCをロックするためのフィールド（RTPヘッダのbytes 8-11）
        self.remote_ssrc: Optional[int] = None

    def connection_made(self, transport):
        self.transport = transport
        # 【デバッグ強化】実際にバインドされたアドレスとポートを確認
        try:
            sock = transport.get_extra_info("socket")
            if sock:
                bound_addr = sock.getsockname()
                self.gateway.logger.debug(
                    "DEBUG_TRACE: [RTP_SOCKET] Bound successfully to: %s",
                    bound_addr,
                )
            else:
                self.gateway.logger.debug(
                    "DEBUG_TRACE: [RTP_SOCKET] Transport created (no socket info available)"
                )
        except Exception as e:
            self.gateway.logger.debug(
                "DEBUG_TRACE: [RTP_SOCKET] connection_made error: %s", e
            )

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        # 【最優先デバッグ】フィルタリング前の「生」の到達を記録（全パケット）
        if not hasattr(self, "_raw_packet_count"):
            self._raw_packet_count = 0
        self._raw_packet_count += 1
        if self._raw_packet_count % 50 == 1:
            print(
                "DEBUG_TRACE: [RTP_RECV_RAW] Received %s bytes from %s (count=%s)"
                % (len(data), addr, self._raw_packet_count),
                flush=True,
            )

        # FreeSWITCH/localhostからのループバックは除外
        if addr[0] in IGNORE_RTP_IPS:
            # FreeSWITCH自身からのパケット（システム音声の逆流）を無視
            if self._raw_packet_count % 100 == 1:
                print(
                    "DEBUG_TRACE: [RTP_FILTER] Ignored packet from local IP: %s (count=%s)"
                    % (addr[0], self._raw_packet_count),
                    flush=True,
                )
            return

        # デバッグ: ユーザーからのパケットのみ処理されることを確認（50回に1回出力）
        if not hasattr(self, "_packet_count"):
            self._packet_count = 0
        self._packet_count += 1
        if self._packet_count % 50 == 1:
            print(
                "DEBUG_TRACE: RTPProtocol packet from user IP=%s port=%s len=%s count=%s"
                % (addr[0], addr[1], len(data), self._packet_count),
                flush=True,
            )

        # 【追加】SSRCフィルタリング（優先）および送信元IP/Portの検証（混線防止）
        try:
            # ヘッダサイズチェック
            if len(data) >= 12:
                try:
                    ssrc = struct.unpack("!I", data[8:12])[0]
                except Exception:
                    ssrc = None
            else:
                ssrc = None

            # SSRCによるロック（存在すれば優先的にチェック）
            if ssrc is not None:
                if self.remote_ssrc is None:
                    self.remote_ssrc = ssrc
                    # IPも記録しておく
                    self.remote_addr = addr
                    self.gateway.logger.info(
                        "[RTP_FILTER] Locked SSRC=%s from %s", ssrc, addr
                    )
                elif self.remote_ssrc != ssrc:
                    # 異なるSSRCは混入と見なし破棄
                    self.gateway.logger.debug(
                        "[RTP_FILTER] Ignored packet with SSRC=%s (expected %s) from %s",
                        ssrc,
                        self.remote_ssrc,
                        addr,
                    )
                    return
            else:
                # SSRC取得できなかった場合はIP/Portで保護（後方互換）
                if self.remote_addr is None:
                    self.remote_addr = addr
                    self.gateway.logger.info(
                        "[RTP_FILTER] Locked remote address to %s", addr
                    )
                elif self.remote_addr != addr:
                    self.gateway.logger.debug(
                        "[RTP_FILTER] Ignored packet from %s (expected %s)",
                        addr,
                        self.remote_addr,
                    )
                    return
        except Exception:
            # フィルタ処理は安全に失敗させない（ログ出力のみ）
            try:
                self.gateway.logger.exception(
                    "[RTP_FILTER] Exception while filtering packet"
                )
            except Exception:
                pass

        # 受信確認ログ（UDPパケットが実際に届いているか確認用）
        self.gateway.logger.debug(
            "[RTP_RECV] Received %s bytes from %s", len(data), addr
        )
        # RTP受信ログ（軽量版：fromとlenのみ）
        self.gateway.logger.info("[RTP_RECV_RAW] from=%s, len=%s", addr, len(data))

        # RakutenのRTP監視対策：受信したパケットをそのまま送り返す（エコー）
        # これによりRakuten側は「RTP到達OK」と判断し、通話が切れなくなる
        try:
            if self.transport:
                self.transport.sendto(data, addr)
                self.gateway.logger.debug(
                    "[RTP_ECHO] sent echo packet to %s, len=%s", addr, len(data)
                )
        except Exception as e:
            self.gateway.logger.warning("[RTP_ECHO] failed to send echo: %s", e)

        try:
            task = asyncio.create_task(self.gateway.handle_rtp_packet(data, addr))

            def log_exception(task: asyncio.Task) -> None:
                exc = task.exception()
                if exc is not None:
                    self.gateway.logger.error(
                        "handle_rtp_packet failed: %r", exc, exc_info=exc
                    )

            task.add_done_callback(log_exception)
        except Exception as e:
            self.gateway.logger.error(
                "Failed to create task for handle_rtp_packet: %r", e, exc_info=True
            )
