# === AF RAW MODE ADDON (nohang) ===
import asyncio
import binascii
import json
import logging
import os
import queue
import socketserver
import sys
import threading
import time
from datetime import datetime

import websockets
from google.cloud import speech
from websockets import exceptions as ws_exceptions

from speech_client_manager import SpeechClientManager
RAW_HOST = os.environ.get("AF_RAW_HOST", "127.0.0.1")
RAW_PORT = int(os.environ.get("AF_RAW_PORT", "9002"))
RAW_LOG  = os.environ.get("AF_RAW_LOG", "/var/log/asr-ws-sink.raw.log")

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

AF_DUMP_MAX_FRAMES = 5
AF_DUMP_MAX_BYTES  = 64
_af_frame_count = 0

def _af_hex(b: bytes) -> str:
    if b is None:
        return ""
    b = b[:AF_DUMP_MAX_BYTES]
    return binascii.hexlify(b).decode("ascii")

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s: %(message)s', stream=sys.stdout)
logger_ws = logging.getLogger('websockets')
logger_ws.setLevel(logging.DEBUG)
logger_ws.addHandler(logging.StreamHandler(sys.stdout))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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

class SilenceHandler:
    def __init__(self, uuid, client_id="000"):
        self.uuid = uuid
        self.client_id = client_id
        self.last_speech_time = None
        self.prompt_count = 0
        self.is_running = True
        self.esl = None
        self._connect_esl()
        self._timer_thread = None

    def _connect_esl(self):
        try:
            sys.path.insert(0, '/opt/libertycall')
            from libs.esl.ESL import ESLconnection
            self.esl = ESLconnection("127.0.0.1", "8021", "ClueCon")
            if not self.esl.connected():
                logger.error("[SILENCE] ESL connection failed uuid=%s", self.uuid)
                self.esl = None
        except Exception as e:
            logger.error("[SILENCE] ESL error uuid=%s err=%s", self.uuid, e)
            self.esl = None

    def _play_audio(self, filename):
        if not self.esl or not self.esl.connected():
            logger.warning("[SILENCE] ESL not connected uuid=%s", self.uuid)
            return False
        audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/{filename}"
        cmd = f"uuid_broadcast {self.uuid} {audio_path} aleg"
        try:
            result = self.esl.api(cmd)
            logger.info("[SILENCE] play uuid=%s file=%s result=%s", self.uuid, filename, result.getBody() if result else "None")
            return True
        except Exception as e:
            logger.error("[SILENCE] play error uuid=%s err=%s", self.uuid, e)
            return False

    def _hangup(self):
        if not self.esl or not self.esl.connected():
            return
        try:
            result = self.esl.api(f"uuid_kill {self.uuid}")
            logger.info("[SILENCE] hangup uuid=%s result=%s", self.uuid, result.getBody() if result else "None")
        except Exception as e:
            logger.error("[SILENCE] hangup error uuid=%s err=%s", self.uuid, e)

    def _timer_loop(self):
        while self.is_running:
            time.sleep(1)
            if self.last_speech_time is None:
                continue
            elapsed = time.time() - self.last_speech_time
            if elapsed >= 10:
                if self.prompt_count == 0:
                    logger.info("[SILENCE] prompt1 uuid=%s elapsed=%.1f", self.uuid, elapsed)
                    self._play_audio("prompt_001_8k.wav")
                    self.prompt_count = 1
                    self.last_speech_time = time.time()
                elif self.prompt_count == 1:
                    logger.info("[SILENCE] prompt2 uuid=%s elapsed=%.1f", self.uuid, elapsed)
                    self._play_audio("prompt_002_8k.wav")
                    self.prompt_count = 2
                    self.last_speech_time = time.time()
                elif self.prompt_count == 2:
                    logger.info("[SILENCE] prompt3 uuid=%s elapsed=%.1f", self.uuid, elapsed)
                    self._play_audio("prompt_003_8k.wav")
                    self.prompt_count = 3
                    time.sleep(17)
                    self.last_speech_time = time.time()
                elif self.prompt_count >= 3:
                    logger.info("[SILENCE] timeout uuid=%s elapsed=%.1f", self.uuid, elapsed)
                    self._hangup()
                    self.is_running = False
                    break

    def reset_timer(self):
        self.last_speech_time = time.time()
        self.prompt_count = 0
        logger.info("[SILENCE] timer_reset uuid=%s", self.uuid)

    def play_greeting(self, gasr_session=None):
        self._play_audio("000.wav")
        time.sleep(5)
        self._play_audio("001.wav")
        time.sleep(2)
        self._play_audio("002.wav")
        time.sleep(2)
        if gasr_session:
            gasr_session.unmute()
        self.start_timer()

    def start_timer(self):
        self.last_speech_time = time.time()
        self.prompt_count = 0
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()
        logger.info("[SILENCE] timer_started uuid=%s", self.uuid)

    def stop(self):
        self.is_running = False

class GoogleStreamingSession:
    def __init__(self, uuid):
        self.uuid = uuid or "unknown"
        self.language = GASR_LANGUAGE
        self.sample_rate = GASR_SAMPLE_RATE
        self.output_path = os.path.join(GASR_OUTPUT_DIR, f"asr_{self.uuid}.jsonl")
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self.queue = queue.Queue()
        self._stop_requested = threading.Event()
        self._closed = threading.Event()
        self.muted = True
        self.client = SpeechClientManager.get_client()
        self.streaming_config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language,
                enable_automatic_punctuation=False,
            ),
            interim_results=True,
            single_utterance=False,
        )
        logger.info("[GASR] session_open uuid=%s config=LINEAR16/%s/%s", self.uuid, self.sample_rate, self.language)
        self._thread = threading.Thread(target=self._consume_responses, daemon=True)
        self._thread.start()

    def send_audio(self, chunk):
        if self._stop_requested.is_set() or not chunk:
            return
        if not hasattr(self, '_skip_count'):
            self._skip_count = 0
        self._skip_count += 1
        if self._skip_count <= 50:
            return
        self.queue.put(chunk)

    def close(self):
        if not self._stop_requested.is_set():
            self._stop_requested.set()
            self.queue.put(None)
        self._closed.wait(timeout=5)

    def _request_generator(self):
        first_chunk = True
        while True:
            chunk = self.queue.get()
            if chunk is None:
                break
            if not chunk:
                continue
            if first_chunk:
                logger.info("[GASR] first_chunk_yielded uuid=%s size=%d", self.uuid, len(chunk))
                first_chunk = False
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    def _consume_responses(self):
        logger.info("[GASR] _consume_responses started uuid=%s", self.uuid)
        try:
            responses = self.client.streaming_recognize(self.streaming_config, requests=self._request_generator())
            logger.info("[GASR] got responses iterator uuid=%s", self.uuid)
            for response in responses:
                self._handle_response(response)
        except Exception as exc:
            logger.exception("[GASR] error uuid=%s detail=%s", self.uuid, exc)
        finally:
            logger.info("[GASR] _consume_responses finished uuid=%s", self.uuid)
            self._closed.set()

    def _handle_response(self, response):
        for result in response.results:
            if not result.alternatives:
                continue
            alt = result.alternatives[0]
            text = alt.transcript or ""
            tag = "final" if result.is_final else "interim"
            logger.info('[GASR] transcript_%s uuid=%s text="%s"', tag, self.uuid, text)
            self._append_transcript(result.is_final, text, alt.confidence)

    def unmute(self):
        self.muted = False
        logger.info("[GASR] unmuted uuid=%s", self.uuid)

    def _append_transcript(self, is_final, transcript, confidence):
        entry = {"timestamp": datetime.utcnow().isoformat() + "Z", "uuid": self.uuid, "is_final": is_final, "transcript": transcript, "confidence": confidence}
        try:
            with open(self.output_path, "a", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
                f.write("\n")
        except Exception:
            pass
        if self.muted:
            return
        cleaned = transcript.strip()
        if not cleaned:
            return
        if len(cleaned) >= 4:
            if not getattr(self, '_dialog_responded', False):
                if hasattr(self, 'silence_handler') and self.silence_handler:
                    self.silence_handler.reset_timer()
                self._handle_dialog(cleaned)
                self._dialog_responded = True
        elif len(cleaned) >= 2 and is_final and confidence >= 0.5:
            if hasattr(self, 'silence_handler') and self.silence_handler:
                self.silence_handler.reset_timer()
            self._handle_dialog(cleaned)
        if is_final:
            self._dialog_responded = False

    def _handle_dialog(self, transcript):
        try:
            sys.path.insert(0, '/opt/libertycall')
            from libs.esl.ESL import ESLconnection
            template = "004"
            logger.info("[DIALOG] uuid=%s input=%s template=%s", self.uuid, transcript, template)
            if not hasattr(self, '_esl') or not self._esl:
                self._esl = ESLconnection("127.0.0.1", "8021", "ClueCon")
            if self._esl and self._esl.connected():
                audio_path = f"/opt/libertycall/clients/000/audio/{template}.wav"
                result = self._esl.api(f"uuid_broadcast {self.uuid} {audio_path} aleg")
                logger.info("[PLAY] uuid=%s template=%s result=%s", self.uuid, template, result.getBody() if result else "None")
        except Exception as e:
            logger.error("[DIALOG] error uuid=%s err=%s", self.uuid, e)

class WSSinkServer:
    def __init__(self):
        self.connections = {}

    async def handle_client(self, websocket):
        global _af_frame_count
        path = getattr(websocket, "path", None)
        call_uuid = _extract_uuid_from_path(path)
        conn_id = str(id(websocket))
        logger.error(f"[AF_WS] connected conn={conn_id} path={path}")
        gasr_session = None
        silence_handler = None
        try:
            gasr_session = GoogleStreamingSession(call_uuid)
            silence_handler = SilenceHandler(call_uuid, client_id="000")
            gasr_session.silence_handler = silence_handler
            silence_handler.play_greeting(gasr_session)
        except Exception as exc:
            logger.exception("[GASR] session_init_failed uuid=%s err=%s", call_uuid, exc)
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
            if silence_handler:
                silence_handler.stop()
            if gasr_session:
                gasr_session.close()

async def main():
    logger.error("Starting WSSink server on ws://0.0.0.0:9000/")
    from speech_client_manager import warmup_speech_client
    await warmup_speech_client()
    async def periodic_warmup():
        while True:
            await asyncio.sleep(60)
            await warmup_speech_client()
    asyncio.create_task(periodic_warmup())
    server = WSSinkServer()
    server_instance = await websockets.serve(server.handle_client, host="0.0.0.0", port=9000, ping_interval=None, max_size=None)
    logger.error("WSSink server started successfully")
    await server_instance.wait_closed()

if __name__ == "__main__":
    _raw_srv = start_raw_server()
    asyncio.run(main())
