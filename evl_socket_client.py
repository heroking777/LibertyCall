#!/usr/bin/env python3
"""EVL - FreeSwitchSocketClient（Event Socket Protocol永続接続クライアント）"""
import socket
import logging

logger = logging.getLogger(__name__)


class FreeSwitchSocketClient:
    """FreeSWITCH Event Socket Protocol 永続接続クライアント"""
    def __init__(self, host="127.0.0.1", port=8021, password="ClueCon"):
        self.socket = socket  # socketモジュールを保持
        self.host = host
        self.port = port
        self.password = password
        self.sock = None
        self._lock = None  # スレッドセーフ用（必要に応じて）

    def connect(self):
        """Event Socketに接続して認証（既に接続済みの場合は再利用）"""
        if self.sock:
            try:
                # 接続が生きているか確認（簡単なテスト）
                self.sock.settimeout(0.1)
                self.sock.recv(1, self.socket.MSG_PEEK)
                self.sock.settimeout(None)
                return  # 既に接続済み
            except (self.socket.error, OSError):
                # 接続が切れている場合は再接続
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

        # 新規接続
        self.sock = self.socket.create_connection((self.host, self.port), timeout=5)

        # バナーを受信
        banner = self.sock.recv(1024).decode('utf-8', errors='ignore')
        logger.debug(f"[FreeSwitchSocketClient] バナー受信: {banner[:50]}")

        if "auth/request" in banner:
            # 認証送信
            auth_cmd = f"auth {self.password}\r\n\r\n"
            self.sock.sendall(auth_cmd.encode('utf-8'))

            # 認証応答を受信
            reply = self.sock.recv(1024).decode('utf-8', errors='ignore')
            logger.debug(f"[FreeSwitchSocketClient] 認証応答: {reply[:50]}")

            if "+OK" not in reply and "accepted" not in reply.lower():
                self.sock.close()
                self.sock = None
                raise Exception(f"認証失敗: {reply[:100]}")

            logger.debug("[FreeSwitchSocketClient] 認証成功")
        else:
            logger.warning(f"[FreeSwitchSocketClient] 認証リクエストが見つかりません: {banner[:50]}")

    def api(self, cmd):
        """APIコマンドを実行して応答を取得"""
        self.connect()  # 接続確認・必要に応じて再接続

        # コマンド送信
        api_cmd = f"api {cmd}\r\n\r\n"
        self.sock.sendall(api_cmd.encode('utf-8'))

        # 応答を受信
        response = b""
        while True:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            response += chunk
            # Content-Lengthを確認して完全な応答を受信
            if b"Content-Length:" in response:
                lines = response.decode('utf-8', errors='ignore').split('\n')
                content_length = 0
                for line in lines:
                    if line.startswith("Content-Length:"):
                        try:
                            content_length = int(line.split(":")[1].strip())
                            break
                        except (ValueError, IndexError):
                            pass

                if content_length > 0:
                    header_end = response.find(b"\n\n")
                    if header_end != -1:
                        body_start = header_end + 2
                        body = response[body_start:]
                        if len(body) >= content_length:
                            break

        response_text = response.decode('utf-8', errors='ignore')

        # ボディ部分を抽出
        body_start = response_text.find("\n\n")
        if body_start != -1:
            body = response_text[body_start + 2:].strip()
            return body
        return response_text.strip()

    def close(self):
        """接続を閉じる"""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
