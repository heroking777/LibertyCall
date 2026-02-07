"""TCP/Unix socket server handling for network manager."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from gateway.common.network_manager import GatewayNetworkManager


class NetworkSocketServer:
    def __init__(self, manager: "GatewayNetworkManager") -> None:
        self.manager = manager
        self.logger = manager.logger
        self.gateway = getattr(manager, "gateway", None)
        self._evt_init()

    def _evt_init(self) -> None:
        has_mgr_gw = hasattr(self.manager, "gateway")
        msg = (
            f"INIT manager={type(self.manager).__name__} has_mgr_gateway={has_mgr_gw} "
            f"self.gateway_type={type(self.gateway).__name__ if self.gateway else None}"
        )
        try:
            os.write(2, f"{time.time():.3f} [EVTSOCK] {msg}\n".encode())
        except Exception:
            pass
        if self.gateway is None:
            raise RuntimeError(
                "NetworkSocketServer: manager.gateway is None (cannot start unix server)"
            )

    def _stderr(self, msg: str) -> None:
        try:
            os.write(2, f"{time.time():.3f} [EVTSOCK_STDERR] {msg}\n".encode())
        except Exception:
            pass

    def _evt(self, msg: str) -> None:
        try:
            os.write(2, f"{time.time():.3f} [EVTSOCK] {msg}\n".encode())
        except Exception:
            pass

    def setup_server_socket(self) -> None:
        """イベントソケットファイルの事前クリーンアップ。"""
        socket_path = Path(self.gateway.event_socket_path)
        if socket_path.exists():
            try:
                socket_path.unlink()
                self.logger.info(
                    "[EVENT_SOCK_UNLINK_PRE] removed stale path=%s",
                    socket_path,
                )
                self._stderr(f"unlink_pre OK path={socket_path}")
            except Exception as e:
                self.logger.warning(
                    "[EVENT_SOCK_UNLINK_PRE_FAIL] path=%s err=%s", socket_path, e,
                    exc_info=True,
                )
                self._stderr(f"unlink_pre FAIL path={socket_path} err={e!r}")

    def cleanup_sockets(self) -> None:
        """イベントソケットファイルの後処理。"""
        socket_path = Path(self.gateway.event_socket_path)
        if socket_path.exists():
            try:
                socket_path.unlink()
                self.logger.info(
                    "[EVENT_SOCK_CLEANUP] removed path=%s",
                    socket_path,
                )
                self._stderr(f"cleanup OK path={socket_path}")
            except Exception as e:
                self.logger.warning(
                    "[EVENT_SOCK_CLEANUP_FAIL] path=%s err=%s", socket_path, e,
                    exc_info=True,
                )
                self._stderr(f"cleanup FAIL path={socket_path} err={e!r}")

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """クライアント接続ハンドラー"""
        gateway = self.gateway
        peer = writer.get_extra_info("peername")
        self._evt(f"CLIENT_ACCEPT peer={peer}")
        try:
            while True:
                self._evt("WAIT_LINE")
                try:
                    line = await reader.readline()
                except BaseException as exc:  # asyncio.CancelledError など
                    self._evt(
                        f"READLINE_BASEEXC type={type(exc).__name__} repr={exc!r}"
                    )
                    raise
                if not line:
                    self._evt("CLIENT_EOF (readline returned empty)")
                    break

                self._evt(
                    f"RECV bytes={len(line)} head={line[:200]!r}"
                )

                try:
                    sock = writer.get_extra_info("socket")
                    fd = sock.fileno() if sock else "?"
                    self._evt(f"SENT_OK_START fd={fd}")
                    writer.write(b"OK\n")
                    await writer.drain()
                    self._evt("SENT_OK_DONE")
                except BaseException as write_exc:
                    self._evt(
                        f"SENT_OK_FAIL type={type(write_exc).__name__} repr={write_exc!r}"
                    )
                    raise

                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    message = json.loads(stripped.decode("utf-8"))
                    evt_type = message.get("event")
                    evt_uuid = message.get("uuid")
                    self._evt(
                        f"GW_EVT_IN type={evt_type} uuid={evt_uuid} keys={list(message.keys())}"
                    )
                    await gateway.router.handle_event_socket_message(message)
                except json.JSONDecodeError as e:
                    self.logger.error("[EVENT_SOCKET] Failed to parse JSON: %s", e)
                except Exception as e:
                    self.logger.exception("[EVENT_SOCKET] Error handling event: %s", e)

        except BaseException as e:
            self.logger.exception("[EVENT_SOCKET] Client handler error: %s", e)
            self._evt(
                f"CLIENT_BASEEXC type={type(e).__name__} repr={e!r}\n"
                + "".join(traceback.format_exception(type(e), e, e.__traceback__))
            )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self._evt("CLIENT_CLOSED")

    async def event_socket_server_loop(self) -> None:
        """
        FreeSWITCHイベント受信用Unixソケットサーバー

        gateway_event_listener.pyからイベントを受信して、
        on_call_start() / on_call_end() を呼び出す
        """
        self.logger.info("[EVENT_SOCK_ENTER] event_socket_server_loop")
        self._evt("event_socket_server_loop ENTER")
        socket_path_raw = getattr(
            self.gateway, "event_socket_path", "/tmp/liberty_gateway_events.sock"
        )
        socket_path = Path(str(socket_path_raw)).expanduser()
        try:
            socket_path = socket_path.resolve()
        except Exception:
            socket_path = Path(str(socket_path))

        exists = socket_path.exists()
        tmp_writable = os.access("/tmp", os.W_OK)
        cwd = os.getcwd()
        pid = os.getpid()
        self.logger.info(
            "[EVENT_SOCK_TRY] path=%s exists=%s tmp_writable=%s cwd=%s pid=%s",
            socket_path,
            exists,
            tmp_writable,
            cwd,
            pid,
        )
        self._evt(
            f"event_socket_server_loop PATH path={socket_path} exists={exists} tmp_writable={tmp_writable} cwd={cwd} pid={pid}"
        )

        if socket_path.exists():
            try:
                socket_path.unlink()
                self.logger.info("[EVENT_SOCK_UNLINK] removed stale path=%s", socket_path)
                self._evt(f"unlink stale OK path={socket_path}")
            except Exception as err:
                self.logger.error(
                    "[EVENT_SOCK_UNLINK_FAIL] path=%s err=%s",
                    socket_path,
                    err,
                    exc_info=True,
                )
                self._evt(f"unlink stale FAIL path={socket_path} err={err!r}")
                raise

        self.setup_server_socket()
        self.logger.info("[EVENT_SOCKET_DEBUG] _event_socket_server_loop started")
        self._stderr(f"event_socket_server_loop ENTER path={socket_path}")
        self._evt(f"event_socket_server_loop SETUP path={socket_path}")

        try:
            self.logger.info("[EVENT_SOCKET_DEBUG] About to start unix server")
            # Unixソケットサーバーを起動
            self._stderr(f"start_unix_server TRY path={socket_path}")
            self._evt(f"start_unix_server TRY path={socket_path}")
            self.gateway.event_server = await asyncio.start_unix_server(
                self.handle_client,
                str(socket_path),
            )
            try:
                st = os.stat(socket_path)
                self._evt(
                    f"start_unix_server SOCKET path={socket_path} ino={st.st_ino}"
                )
            except Exception as stat_exc:
                self._evt(
                    f"start_unix_server SOCKET_STAT_FAIL path={socket_path} err={stat_exc!r}"
                )
            self._stderr(f"start_unix_server OK path={socket_path}")
            self._evt(
                f"start_unix_server OK path={socket_path} sockets={getattr(self.gateway.event_server, 'sockets', None)}"
            )
            self.logger.info(
                "[EVENT_SOCK_OK] listening path=%s exists_now=%s",
                socket_path,
                socket_path.exists(),
            )
            # サーバーが停止するまで待機
            async with self.gateway.event_server:
                self._evt(
                    f"serve_forever ENTER path={socket_path} server={self.gateway.event_server}"
                )
                await self.gateway.event_server.serve_forever()
                self._evt(
                    f"serve_forever EXIT path={socket_path} server={self.gateway.event_server}"
                )
        except Exception as e:
            self.logger.error(
                "[EVENT_SOCK_FAIL] path=%s errno=%s err=%s",
                socket_path,
                getattr(e, "errno", None),
                e,
                exc_info=True,
            )
            self._stderr(f"start_unix_server FAIL path={socket_path} err={e!r}")
            trace = "".join(
                traceback.format_exception(type(e), e, e.__traceback__)
            )
            self._evt(f"start_unix_server FAIL path={socket_path} err={e!r}")
            os.write(2, trace.encode())
            raise
        finally:
            # クリーンアップ
            self.cleanup_sockets()
            self._evt(f"cleanup DONE path={socket_path}")
