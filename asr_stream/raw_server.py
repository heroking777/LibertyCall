"""AF RAW MODE ADDON (nohang) - デバッグ用TCPサーバー"""
import os
import socketserver
import threading
import time

RAW_HOST = os.environ.get("AF_RAW_HOST", "127.0.0.1")
RAW_PORT = int(os.environ.get("AF_RAW_PORT", "9002"))
RAW_LOG = os.environ.get("AF_RAW_LOG", "/var/log/asr-ws-sink.raw.log")


class _RawHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            peer = self.request.getpeername()
        except Exception:
            peer = ("?", 0)
        with open(RAW_LOG, "a", encoding="utf-8") as f:
            f.write(f"[AF_RAW] connect {peer}\n")
        buf = b""
        try:
            self.request.settimeout(2.0)
            buf = self.request.recv(16) or b""
        except Exception:
            pass
        with open(RAW_LOG, "a", encoding="utf-8") as f:
            f.write(f"[AF_RAW] first16={buf!r}\n")
        total = len(buf)
        start = time.time()
        try:
            while True:
                if time.time() - start > 3.0:
                    break
                self.request.settimeout(0.5)
                chunk = self.request.recv(4096)
                if not chunk:
                    break
                total += len(chunk)
        except Exception:
            pass
        with open(RAW_LOG, "a", encoding="utf-8") as f:
            f.write(f"[AF_RAW] done {peer} bytes={total}\n")
        try:
            self.request.close()
        except Exception:
            pass


class _ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def start_raw_server():
    srv = _ReusableTCPServer((RAW_HOST, RAW_PORT), _RawHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv
