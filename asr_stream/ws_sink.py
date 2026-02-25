from raw_server import start_raw_server
import asyncio
import binascii
import json
import logging
import os
import queue
import socketserver
import struct
import sys
import threading
import time
from datetime import datetime

import websockets
from google.cloud import speech
from websockets import exceptions as ws_exceptions

from speech_client_manager import SpeechClientManager
from call_logger import CallLogger

# importをファイル先頭で一度だけ実行
sys.path.insert(0, '/opt/libertycall')
from gateway.dialogue.dialogue_flow import get_response, get_action
from libs.esl.ESL import ESLconnection

from logging.handlers import RotatingFileHandler

# ログローテーション設定
handler = RotatingFileHandler(
    '/tmp/ws_sink_debug.log',
    maxBytes=5*1024*1024,  # 5MB
    backupCount=3
)
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

logging.basicConfig(level=logging.INFO, handlers=[handler])
logger_ws = logging.getLogger('websockets')
logger_ws.setLevel(logging.WARNING)
logger_ws.addHandler(logging.StreamHandler(sys.stdout))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

GASR_SAMPLE_RATE = int(os.environ.get("GASR_SAMPLE_RATE", "8000"))
GASR_LANGUAGE = os.environ.get("GASR_LANGUAGE", "ja-JP")
GASR_OUTPUT_DIR = os.environ.get("GASR_OUTPUT_DIR", "/tmp")

def _extract_uuid_from_path(path):
    if not path:
        return "unknown"
    trimmed = path.strip("/")
    if not trimmed:
        return "unknown"
    parts = trimmed.split("/")
    if parts[0] == "u" and len(parts) >= 2:
        candidate = parts[1]
    else:
        candidate = parts[-1]
    candidate = candidate.strip()
    if not candidate:
        return "unknown"
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in candidate) or "unknown"

from silence_handler import SilenceHandler
from gasr_session import GoogleStreamingSession
class WSSinkServer:
    def __init__(self):
        self.connections = {}
        self.esl = None
        self._connect_esl()
        self._active_sessions = set()  # Track active sessions for warmup control

    def _connect_esl(self):
        try:
            sys.path.insert(0, '/opt/libertycall')
            from libs.esl.ESL import ESLconnection
            for attempt in range(10):
                self.esl = ESLconnection("127.0.0.1", "8021", "ClueCon")
                if self.esl.connected():
                    break
                logger.warning("[WS_SERVER] ESL connect attempt %d/10 failed, retrying in 3s...", attempt+1)
                import time; time.sleep(3)
            if self.esl.connected():
                self.esl.send("noevents")
                self.esl.recvEvent()  # consume reply
            else:
                logger.error("[WS_SERVER] ESL connection failed")
                self.esl = None
        except Exception as e:
            logger.error("[WS_SERVER] ESL error err=%s", e)
            self.esl = None

    def _get_client_id_from_uuid(self, uuid):
        try:
            logger.info(f"[WS_SERVER] Getting client_id for uuid={uuid}")
            if not self.esl or not self.esl.connected():
                logger.warning(f"[WS_SERVER] ESL not connected for uuid={uuid}, reconnecting...")
                self._connect_esl()
                if not self.esl or not self.esl.connected():
                    logger.error(f"[WS_SERVER] ESL reconnect failed for uuid={uuid}")
                    return "000"
            result = self.esl.api(f"uuid_getvar {uuid} destination_number")
            dest_number = result.getBody() if result else "unknown"
            logger.info(f"[WS_SERVER] Got destination_number={dest_number} for uuid={uuid}")
            
            with open('/opt/libertycall/config/phone_mapping.json') as f:
                mapping = json.load(f)
            
            client_id = mapping.get(dest_number, "000")
            logger.info(f"[WS_SERVER] Mapped {dest_number} -> client_id={client_id}")
            return client_id
        except Exception as e:
            logger.error(f"[WS_SERVER] Error getting client_id for uuid={uuid}: {e}")
            return "000"

    async def handle_client(self, websocket):
        path = getattr(websocket, "path", None) or getattr(getattr(websocket, "request", None), "path", None)
        call_uuid = _extract_uuid_from_path(path)
        conn_id = str(id(websocket))
        logger.error(f"[AF_WS] connected conn={conn_id} path={path}")
        
        # 同一UUIDの重複接続を拒否
        if call_uuid in self.connections:
            logger.warning(f"[AF_WS] duplicate uuid={call_uuid} conn={conn_id}, rejecting")
            await websocket.close()
            return
        self.connections[call_uuid] = conn_id
        self._active_sessions.add(call_uuid)  # Add to active sessions
        
        gasr_session = None
        silence_handler = None
        call_logger = None
        recording_started = False
        try:
            client_id = self._get_client_id_from_uuid(call_uuid)
            logger.info(f"[WS_SERVER] uuid={call_uuid} dest_number mapped to client_id={client_id}")
            # 発信者番号を取得
            caller_number = "番号不明"
            try:
                if self.esl and self.esl.connected():
                    cn_result = self.esl.api(f"uuid_getvar {call_uuid} caller_id_number")
                    cn_body = cn_result.getBody().strip() if cn_result else ""
                    if cn_body and cn_body != "_undef_" and cn_body != "NONE":
                        caller_number = cn_body
                    logger.info(f"[WS_SERVER] caller_number={caller_number} for uuid={call_uuid}")
            except Exception as e:
                logger.warning(f"[WS_SERVER] Failed to get caller_number: {e}")
            call_logger = CallLogger(call_uuid, client_id, caller_number=caller_number)
            
            # === 両方向録音開始（ESL経由 uuid_record） ===
            rec_path = call_logger.get_recording_path()
            for _esl_attempt in range(2):
                try:
                    if not self.esl or not self.esl.connected():
                        logger.warning("[WS_SERVER] ESL not connected, reconnecting uuid=%s", call_uuid)
                        self._connect_esl()
                    self.esl.api(f"uuid_setvar {call_uuid} RECORD_STEREO true")
                    rec_result = self.esl.api(f"uuid_record {call_uuid} start {rec_path}")
                    break
                except Exception as esl_err:
                    logger.warning("[WS_SERVER] ESL call failed attempt=%d uuid=%s err=%s", _esl_attempt+1, call_uuid, esl_err)
                    self._connect_esl()
                    rec_result = None
            if self.esl and self.esl.connected():
                rec_body = rec_result.getBody() if rec_result else "NO_RESULT"
                if rec_result and "+OK" in str(rec_body):
                    recording_started = True
                    logger.info("[RECORDING] started uuid=%s path=%s", call_uuid, rec_path)
                else:
                    logger.error("[RECORDING] failed uuid=%s result=%s", call_uuid, rec_body)
            else:
                logger.error("[RECORDING] ESL not connected, skipping recording uuid=%s", call_uuid)
            
            gasr_session = GoogleStreamingSession(call_uuid, client_id=client_id)
            silence_handler = SilenceHandler(call_uuid, client_id=client_id)
            gasr_session.silence_handler = silence_handler
            gasr_session.call_logger = call_logger
            await asyncio.get_event_loop().run_in_executor(None, silence_handler.play_greeting, gasr_session)
        except Exception as exc:
            logger.exception("[GASR] session_init_failed uuid=%s err=%s", call_uuid, exc)
            self.connections.pop(call_uuid, None)
            return
        total = 0
        try:
            async for message in websocket:
                if isinstance(message, str) and message.strip() == "{}":
                    await websocket.send('{"ok":true}')
                    continue
                if not isinstance(message, (bytes, bytearray)):
                    continue
                total += len(message)
                if gasr_session:
                    gasr_session.send_audio(bytes(message))
        except Exception as e:
            logger.info(f"[AF_WS] conn={conn_id} closed {type(e).__name__}")
        finally:
            logger.error(f"[AF_WS] disconnected conn={conn_id} total={total}")
            self.connections.pop(call_uuid, None)
            self._active_sessions.discard(call_uuid)  # Remove from active sessions
            if recording_started and self.esl and self.esl.connected():
                self.esl.api(f"uuid_record {call_uuid} stop all")
                logger.info("[RECORDING] stopped uuid=%s", call_uuid)
            if recording_started and call_logger:
                try:
                    rec_file = call_logger.get_recording_path()
                    if os.path.exists(rec_file):
                        import subprocess
                        subprocess.run(["sudo", "chown", "deploy:deploy", rec_file], timeout=5, capture_output=True)
                        logger.info("[RECORDING] chown done uuid=%s", call_uuid)
                except Exception as e:
                    logger.warning("[RECORDING] chown failed uuid=%s err=%s", call_uuid, e)
            if silence_handler:
                silence_handler.stop()
            if gasr_session:
                gasr_session.close()
            if call_logger:
                call_logger.close()

async def main():
    logger.error("Starting WSSink server on ws://0.0.0.0:9000/")
    from speech_client_manager import warmup_speech_client
    await warmup_speech_client()
    
    server = WSSinkServer()
    
    async def periodic_warmup():
        while True:
            await asyncio.sleep(60)
            # Only warmup if no active sessions to prevent OOM during calls
            if not server._active_sessions:
                await warmup_speech_client()
                logger.info("[WARMUP] Periodic warmup completed (no active sessions)")
            else:
                logger.info(f"[WARMUP] Skipping warmup - {len(server._active_sessions)} active sessions")
    
    asyncio.create_task(periodic_warmup())
    server_instance = await websockets.serve(server.handle_client, host="0.0.0.0", port=9000, ping_interval=None, max_size=None)
    logger.error("WSSink server started successfully")
    await server_instance.wait_closed()

if __name__ == "__main__":
    _raw_srv = start_raw_server()
    asyncio.run(main())


