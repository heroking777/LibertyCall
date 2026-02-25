"""WebSocket sink server for Whisper ASR (port 8083)"""
import asyncio
import json
import logging
import os
import sys
import time

import websockets
from websockets import exceptions as ws_exceptions

from call_logger import CallLogger

sys.path.insert(0, '/opt/libertycall')
from libs.esl.ESL import ESLconnection

from logging.handlers import RotatingFileHandler

# Logging setup
handler = RotatingFileHandler(
    '/tmp/ws_sink_whisper_debug.log',
    maxBytes=5*1024*1024,
    backupCount=3
)
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

logging.basicConfig(level=logging.DEBUG, handlers=[handler])
logger_ws = logging.getLogger('websockets')
logger_ws.setLevel(logging.WARNING)
logger_ws.addHandler(logging.StreamHandler(sys.stdout))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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
from whisper_session import WhisperStreamingSession


class WhisperWSSinkServer:
    def __init__(self):
        self.connections = {}
        self.esl = None
        self._connect_esl()

    def _esl_api(self, cmd):
        """ESL API call with auto-reconnect on Broken pipe"""
        for attempt in range(2):
            try:
                if not self.esl or not self.esl.connected():
                    self._connect_esl()
                if self.esl and self.esl.connected():
                    result = self.esl.api(cmd)
                    return result
            except BrokenPipeError:
                logger.warning("[ESL] Broken pipe, reconnecting (attempt %d)", attempt + 1)
                self.esl = None
                self._connect_esl()
            except Exception as e:
                logger.error("[ESL] api error: %s", e)
                return None
        return None

    def _connect_esl(self):
        try:
            self.esl = ESLconnection("127.0.0.1", "8021", "ClueCon")
            if not self.esl.connected():
                logger.error("[WS_SERVER] ESL connection failed")
                self.esl = None
        except Exception as e:
            logger.error("[WS_SERVER] ESL error err=%s", e)
            self.esl = None

    def _get_client_id_from_uuid(self, uuid):
        try:
            if not self.esl or not self.esl.connected():
                return "whisper_test"
            result = self._esl_api(f"uuid_getvar {uuid} destination_number")
            dest_number = result.getBody() if result else "unknown"
            logger.info("[WS_SERVER] destination_number=%s uuid=%s", dest_number, uuid)

            with open('/opt/libertycall/config/phone_mapping.json') as f:
                mapping = json.load(f)

            client_id = mapping.get(dest_number, "whisper_test")
            logger.info("[WS_SERVER] mapped -> client_id=%s", client_id)
            return client_id
        except Exception as e:
            logger.error("[WS_SERVER] Error getting client_id: %s", e)
            return "whisper_test"

    async def handle_client(self, websocket):
        path = getattr(websocket, "path", None) or getattr(getattr(websocket, "request", None), "path", None)
        call_uuid = _extract_uuid_from_path(path)
        conn_id = str(id(websocket))
        logger.error("[AF_WS] connected conn=%s path=%s", conn_id, path)

        if call_uuid in self.connections:
            logger.warning("[AF_WS] duplicate uuid=%s, rejecting", call_uuid)
            await websocket.close()
            return
        self.connections[call_uuid] = conn_id

        whisper_session = None
        silence_handler = None
        call_logger = None
        recording_started = False
        try:
            client_id = self._get_client_id_from_uuid(call_uuid)
            # Get caller number for call log
            caller_number = ""
            try:
                cn_result = self._esl_api(f"uuid_getvar {call_uuid} caller_id_number")
                if cn_result:
                    caller_number = cn_result.getBody().strip() if cn_result.getBody() else ""
                logger.info("[WS_SERVER] caller_number=%s uuid=%s", caller_number, call_uuid)
            except Exception as e:
                logger.warning("[WS_SERVER] failed to get caller_number: %s", e)
            call_logger = CallLogger(call_uuid, client_id, caller_number=caller_number)

            # Recording
            rec_path = call_logger.get_recording_path()
            if self.esl and self.esl.connected():
                self._esl_api(f"uuid_setvar {call_uuid} RECORD_STEREO true")
                rec_result = self._esl_api(f"uuid_record {call_uuid} start {rec_path}")
                rec_body = rec_result.getBody() if rec_result else "NO_RESULT"
                if rec_result and "+OK" in str(rec_body):
                    recording_started = True
                    logger.info("[RECORDING] started uuid=%s path=%s", call_uuid, rec_path)
                else:
                    logger.error("[RECORDING] failed uuid=%s result=%s", call_uuid, rec_body)

            whisper_session = WhisperStreamingSession(call_uuid, client_id=client_id)
            silence_handler = SilenceHandler(call_uuid, client_id=client_id)
            whisper_session.silence_handler = silence_handler
            whisper_session.call_logger = call_logger
            silence_handler.play_greeting(whisper_session)
        except Exception as exc:
            logger.exception("[WHISPER] session_init_failed uuid=%s err=%s", call_uuid, exc)
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
                if whisper_session:
                    whisper_session.send_audio(bytes(message))
        except Exception as e:
            logger.info("[AF_WS] conn=%s closed %s", conn_id, type(e).__name__)
        finally:
            logger.error("[AF_WS] disconnected conn=%s total=%d", conn_id, total)
            self.connections.pop(call_uuid, None)
            if recording_started and self.esl and self.esl.connected():
                self._esl_api(f"uuid_record {call_uuid} stop all")
            if recording_started and call_logger:
                try:
                    rec_file = call_logger.get_recording_path()
                    if os.path.exists(rec_file):
                        import subprocess
                        subprocess.run(["sudo", "chown", "deploy:deploy", rec_file],
                                     timeout=5, capture_output=True)
                except Exception:
                    pass
            if silence_handler:
                silence_handler.stop()
            if whisper_session:
                whisper_session.close()
            if call_logger:
                call_logger.close()


async def main():
    logger.error("Starting Whisper WSSink server on ws://0.0.0.0:8083/")

    # Pre-load Whisper model
    from whisper_session import get_whisper_model
    logger.info("[STARTUP] Pre-loading Whisper model...")
    get_whisper_model()
    logger.info("[STARTUP] Whisper model ready")

    # Pre-load LLM model for whisper_test client
    try:
        from gateway.dialogue.llm_handler import LLMDialogueHandler
        logger.info("[STARTUP] Pre-loading LLM model...")
        llm_handler = LLMDialogueHandler.get_instance()
        # Trigger model loading and ensure _loaded flag is set
        if llm_handler._ensure_loaded():
            LLMDialogueHandler._loaded = True  # Ensure the class-level flag is properly set
            logger.info("[STARTUP] LLM model ready")
        else:
            logger.warning("[STARTUP] LLM model failed to load")
    except Exception as e:
        logger.error("[STARTUP] LLM preload error: %s", e)

    server = WhisperWSSinkServer()
    server_instance = await websockets.serve(
        server.handle_client, host="0.0.0.0", port=8083,
        ping_interval=None, max_size=None)
    logger.error("Whisper WSSink server started successfully on port 8083")
    await server_instance.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
