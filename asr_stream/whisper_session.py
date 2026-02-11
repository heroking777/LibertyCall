"""WhisperStreamingSession - faster-whisper based ASR session."""
import io
import json
import logging
import os
import queue
import struct
import sys
import threading
import time
import wave
import numpy as np

from faster_whisper import WhisperModel

from call_logger import CallLogger
from gasr_dialog_handler import GASRDialogHandlerMixin

sys.path.insert(0, '/opt/libertycall')
from libs.esl.ESL import ESLconnection

logger = logging.getLogger(__name__)

GASR_SAMPLE_RATE = int(os.environ.get("GASR_SAMPLE_RATE", "8000"))
GASR_LANGUAGE = os.environ.get("GASR_LANGUAGE", "ja-JP")
GASR_OUTPUT_DIR = os.environ.get("GASR_OUTPUT_DIR", "/tmp")

# Whisper model singleton (shared across sessions)
_whisper_model = None
_whisper_lock = threading.Lock()

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                model_size = os.environ.get("WHISPER_MODEL", "tiny")
                device = os.environ.get("WHISPER_DEVICE", "cpu")
                compute_type = os.environ.get("WHISPER_COMPUTE", "int8")
                logger.info("[WHISPER] Loading model=%s device=%s compute=%s",
                           model_size, device, compute_type)
                start = time.time()
                _whisper_model = WhisperModel(
                    model_size, device=device, compute_type=compute_type)
                logger.info("[WHISPER] Model loaded in %.2fs", time.time() - start)
    return _whisper_model


class WhisperStreamingSession(GASRDialogHandlerMixin):
    def __init__(self, uuid, client_id="whisper_test"):
        self.uuid = uuid or "unknown"
        self.client_id = client_id
        self.language = "ja"
        self.sample_rate = GASR_SAMPLE_RATE
        self.output_path = os.path.join(GASR_OUTPUT_DIR, f"asr_{self.uuid}.jsonl")
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self.queue = queue.Queue()
        self._stop_requested = threading.Event()
        self._closed = threading.Event()
        self.muted = True
        self._current_phase = "QA"
        self._dialog_state = {}
        self._accumulated_text = ""
        self._silence_timer = None
        self._is_playing = False
        self._is_speaking = False
        self._responded_offset = 0
        self._extended_once = False
        self._last_responded_text = ""
        self._interim_responded = False

        # Whisper model (shared singleton)
        self._model = get_whisper_model()

        # Audio buffer for Whisper (collect chunks, transcribe on silence)
        self._audio_buffer = bytearray()
        self._last_voice_time = None
        self._vad_threshold = int(os.environ.get("WHISPER_VAD_THRESHOLD", "1500"))
        self._silence_duration_trigger = float(os.environ.get("WHISPER_SILENCE_TRIGGER", "0.5"))

        # voice_map
        self._voice_map = self._load_voice_list()

        # dialogue_config
        self._dialogue_config = self._load_dialogue_config()

        # ESL
        self._esl = None
        self._connect_esl()

        # instant keywords
        phrase_hints = self._load_phrase_hints()
        self._instant_keywords = set(phrase_hints) if phrase_hints else set()
        logger.info("[WHISPER] instant_keywords loaded count=%d uuid=%s",
                   len(self._instant_keywords), self.uuid)

        logger.info("[WHISPER] session_open uuid=%s model=%s sample_rate=%d",
                    self.uuid, os.environ.get("WHISPER_MODEL", "tiny"), self.sample_rate)

    # ------------------------------------------------------------------ #
    #  Config loaders (same as gasr_session.py)
    # ------------------------------------------------------------------ #
    def _load_dialogue_config(self):
        config_path = f"/opt/libertycall/clients/{self.client_id}/config/dialogue_config.json"
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info("[WHISPER] dialogue_config loaded uuid=%s", self.uuid)
            return config
        except Exception as e:
            logger.warning("[WHISPER] dialogue_config load failed uuid=%s err=%s", self.uuid, e)
            return {}

    def _load_phrase_hints(self):
        config = self._dialogue_config
        if not config:
            return []
        hints = set()
        for pattern in config.get("patterns", []):
            for kw in pattern.get("keywords", []):
                hints.add(kw)
        return list(hints)

    def _load_voice_list(self):
        self._voice_map = {}
        try:
            with open(f'/opt/libertycall/clients/{self.client_id}/voice_list_{self.client_id}.tsv',
                      'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        self._voice_map[parts[0]] = parts[1]
        except Exception as e:
            logger.warning("[VOICE] Failed to load voice_list: %s", e)
        return self._voice_map

    # ------------------------------------------------------------------ #
    #  Audio input
    # ------------------------------------------------------------------ #
    def send_audio(self, chunk):
        if self._stop_requested.is_set() or not chunk:
            return
        if self.muted:
            return

        # Flush old buffered audio after unmute
        if hasattr(self, '_flush_until') and time.time() < self._flush_until:
            return

        # First audio timestamp
        if not hasattr(self, '_first_audio_time'):
            self._first_audio_time = time.time()
            logger.info("[TIMING] first_audio_received uuid=%s", self.uuid)

        # BARGE_IN detection
        if self._is_playing:
            try:
                samples = struct.unpack(f'<{len(chunk)//2}h', chunk)
                amplitude = sum(abs(s) for s in samples) / len(samples)
                if amplitude > 3000:
                    if not hasattr(self, '_barge_in_count'):
                        self._barge_in_count = 0
                    self._barge_in_count += 1
                    if self._barge_in_count >= 3:
                        logger.info("[BARGE_IN] detected uuid=%s", self.uuid)
                        self._stop_current_playback()
                        self._is_playing = False
                        self._barge_in_count = 0
                else:
                    self._barge_in_count = 0
            except Exception:
                pass

        # VAD: check if this chunk contains voice
        try:
            samples = struct.unpack(f'<{len(chunk)//2}h', chunk)
            amplitude = sum(abs(s) for s in samples) / len(samples)
        except Exception:
            amplitude = 0

        now = time.time()

        if amplitude > self._vad_threshold:
            # Voice detected
            self._last_voice_time = now
            self._audio_buffer.extend(chunk)
            self._is_speaking = True
        else:
            # Silence
            if self._is_speaking and self._audio_buffer:
                self._audio_buffer.extend(chunk)
                # Check if silence long enough to trigger transcription
                if self._last_voice_time and (now - self._last_voice_time) >= self._silence_duration_trigger:
                    self._transcribe_buffer()
                    self._is_speaking = False

        # Silence handler
        try:
            if hasattr(self, 'silence_handler') and self.silence_handler:
                self.silence_handler.detect_silence(chunk)
        except Exception as e:
            logger.warning("[SILENCE_DETECT] error uuid=%s err=%s", self.uuid, e)

    # ------------------------------------------------------------------ #
    #  Whisper transcription
    # ------------------------------------------------------------------ #
    def _transcribe_buffer(self):
        if not self._audio_buffer:
            return

        audio_data = bytes(self._audio_buffer)
        self._audio_buffer = bytearray()
        buffer_duration = len(audio_data) / (self.sample_rate * 2)

        logger.info("[WHISPER] transcribing uuid=%s duration=%.2fs",
                   self.uuid, buffer_duration)

        # Skip very short audio (< 0.3s)
        if buffer_duration < 0.3:
            logger.info("[WHISPER] skip too short uuid=%s duration=%.2f",
                       self.uuid, buffer_duration)
            return

        try:
            start_time = time.time()

            # Convert 8kHz 16-bit PCM to 16kHz float32 for Whisper
            audio_16k = self._resample_8k_to_16k(audio_data)

            # Run Whisper inference
            segments, info = self._model.transcribe(
                audio_16k,
                language="ja",
                beam_size=1,
                best_of=1,
                vad_filter=False,
                without_timestamps=True,
            )

            # Collect results
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            full_text = "".join(text_parts).strip()
            elapsed = time.time() - start_time

            logger.info('[WHISPER] result uuid=%s elapsed=%.3fs text="%s"',
                       self.uuid, elapsed, full_text)

            if full_text:
                # Log ASR result
                if hasattr(self, 'call_logger') and self.call_logger:
                    self.call_logger.log_asr(full_text, True, 0.0)

                # Process as final result
                self._append_transcript(True, full_text, 0.0)

        except Exception as e:
            logger.error("[WHISPER] transcription error uuid=%s err=%s", self.uuid, e)

    def _resample_8k_to_16k(self, pcm_data):
        """8kHz 16-bit PCM -> 16kHz float32 numpy array for Whisper"""
        # Decode 16-bit PCM
        samples_8k = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Simple linear interpolation for 8k -> 16k
        n = len(samples_8k)
        indices_16k = np.arange(0, n, 0.5)
        indices_16k = indices_16k[indices_16k < n]
        samples_16k = np.interp(indices_16k, np.arange(n), samples_8k)

        return samples_16k.astype(np.float32)

    # ------------------------------------------------------------------ #
    #  Session lifecycle
    # ------------------------------------------------------------------ #
    def close(self):
        if not self._stop_requested.is_set():
            self._stop_requested.set()
            # Transcribe remaining buffer
            if self._audio_buffer:
                self._transcribe_buffer()
        self._closed.set()

    def unmute(self):
        self.muted = False
        self._unmute_time = time.time()
        self._flush_until = self._unmute_time + 0.2
        logger.info("[WHISPER] unmuted uuid=%s", self.uuid)

    # ------------------------------------------------------------------ #
    #  ESL connection
    # ------------------------------------------------------------------ #
    def _connect_esl(self):
        try:
            self._esl = ESLconnection("127.0.0.1", "8021", "ClueCon")
            if self._esl.connected():
                logger.info("[ESL] connected uuid=%s", self.uuid)
            else:
                logger.error("[ESL] connection failed uuid=%s", self.uuid)
                self._esl = None
        except Exception as e:
            logger.error("[ESL] error uuid=%s err=%s", self.uuid, e)
            self._esl = None
