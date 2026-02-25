"""WhisperStreamingSession - faster-whisper based ASR session."""
from asr_stream.embedding_classifier import EmbeddingClassifier
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
        self._vad_threshold = 300  # Fixed threshold for low-amplitude audio
        logger.info("[WHISPER] VAD threshold set to %d", self._vad_threshold)
        self._silence_duration_trigger = float(os.environ.get("WHISPER_SILENCE_TRIGGER", "0.5"))
        
        # Periodic transcription for real-time processing
        self._periodic_timer = None
        self._periodic_interval = float(os.environ.get("WHISPER_PERIODIC_INTERVAL", "2.5"))  # seconds
        self._last_transcribe_time = 0

        # voice_map
        self._voice_map = self._load_voice_list()

        # dialogue_config
        self._dialogue_config = self._load_dialogue_config()

        from intent_wrapper import IntentWrapper
        self._streaming_llm = IntentWrapper(self.client_id)

        # Embedding classifier
        try:
            self._emb_clf = EmbeddingClassifier()
            self._responding = False
            self._emb_clf.set_ct_model(self._model.model)
            logger.info("[EMB_CLF] classifier ready for uuid=%s", self.uuid)
        except Exception as e:
            self._emb_clf = None
            logger.warning("[EMB_CLF] failed to load: %s", e)

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
    def _schedule_periodic_transcribe(self):
        """Schedule periodic transcription for real-time processing"""
        if self._periodic_timer and self._periodic_timer.is_alive():
            return
        
        logger.info("[PERIODIC] starting timer uuid=%s interval=%.1fs", self.uuid, self._periodic_interval)
        self._periodic_timer = threading.Timer(self._periodic_interval, self._periodic_transcribe)
        self._periodic_timer.daemon = True
        self._periodic_timer.start()
    
    def _periodic_transcribe(self):
        """Periodic transcription callback"""
        current_time = time.time()
        
        # Only transcribe if we have enough audio and haven't transcribed recently
        if (self._audio_buffer and 
            current_time - self._last_transcribe_time >= self._periodic_interval and
            len(self._audio_buffer) >= self.sample_rate * 2 * 1.0):  # At least 1 second of audio
            
            logger.info("[PERIODIC] transcribing uuid=%s buffer_size=%d", 
                       self.uuid, len(self._audio_buffer))
            self._transcribe_buffer(interim=True)
            self._last_transcribe_time = current_time
        
        # Schedule next periodic transcription if still speaking
        if self._is_speaking:
            self._schedule_periodic_transcribe()

    def send_audio(self, chunk):
        if self._stop_requested.is_set() or not chunk:
            return
        if self.muted:
            return

        # Flush old buffered audio after unmute
        if hasattr(self, '_flush_until') and time.time() < self._flush_until:
            return

        # Reset speaking state when first audio arrives after greeting
        if hasattr(self, '_greeting_complete') and self._greeting_complete:
            self._is_speaking = False
            self._greeting_complete = False
            logger.info("[VAD] reset speaking state after greeting uuid=%s", self.uuid)

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
            
            # Start periodic transcription if not already running
            if not self._is_speaking:
                self._is_speaking = True
                logger.info("[VAD] voice detected uuid=%s amplitude=%.0f", self.uuid, amplitude)
                self._schedule_periodic_transcribe()
            else:
                logger.debug("[VAD] continuing speech uuid=%s amplitude=%.0f", self.uuid, amplitude)
        else:
            # Silence - still collect audio but don't trigger immediate transcription
            if self._is_speaking and self._audio_buffer:
                self._audio_buffer.extend(chunk)
                # Check if silence long enough to trigger final transcription
                if self._last_voice_time and (now - self._last_voice_time) >= self._silence_duration_trigger:
                    self._transcribe_buffer()  # Final transcription
                    self._is_speaking = False
                    # Cancel periodic timer
                    if self._periodic_timer:
                        self._periodic_timer.cancel()
                        self._periodic_timer = None

        # Silence handler
        try:
            if hasattr(self, 'silence_handler') and self.silence_handler:
                self.silence_handler.detect_silence(chunk)
        except Exception as e:
            logger.warning("[SILENCE_DETECT] error uuid=%s err=%s", self.uuid, e)

    # ------------------------------------------------------------------ #
    #  Whisper transcription
    # ------------------------------------------------------------------ #
    def _transcribe_buffer(self, interim=False):
        if not self._audio_buffer:
            return

        audio_data = bytes(self._audio_buffer)
        
        # For interim processing, keep the buffer for next transcription
        if not interim:
            self._audio_buffer = bytearray()
        
        buffer_duration = len(audio_data) / (self.sample_rate * 2)

        logger.info("[WHISPER] transcribing uuid=%s duration=%.2fs interim=%s",
                   self.uuid, buffer_duration, interim)

        # Skip very short audio (< 0.3s for final, < 1.0s for interim)
        min_duration = 1.0 if interim else 0.3
        if buffer_duration < min_duration:
            logger.info("[WHISPER] skip too short uuid=%s duration=%.2f interim=%s",
                       self.uuid, buffer_duration, interim)
            return

        try:
            start_time = time.time()

            # Convert 8kHz 16-bit PCM to 16kHz float32 for Whisper
            audio_16k = self._resample_8k_to_16k(audio_data)

            # --- Embedding classifier (primary) ---
            if self._emb_clf:
                try:
                    # Skip if already responding
                    if getattr(self, '_responding', False) or getattr(self, '_muted', False) or getattr(self, 'muted', False):
                        logger.info("[EMB_CLF] skipping - already responding or muted")
                        return
                    # _responding is set in _trigger_immediate_response
                    # Skip short buffers (likely announcement residue)
                    audio_duration = len(audio_16k) / 16000.0
                    if audio_duration < 1.5:
                        logger.info("[EMB_CLF] skipping short buffer %.1fs", audio_duration)
                        return
                    emb_label, emb_conf = self._emb_clf.classify(audio_16k)
                    # Re-check if another buffer already triggered response
                    if getattr(self, '_muted', False) or getattr(self, 'muted', False):
                        logger.info("[EMB_CLF] skipping - muted after classify")
                        self._responding = False
                        return
                    logger.info("[EMB_CLF] uuid=%s label=%s conf=%.3f duration=%.2fs",
                               self.uuid, emb_label, emb_conf, buffer_duration)
                    if emb_conf >= 0.50:
                        elapsed_emb = time.time() - start_time
                        logger.info('[EMB_CLF] result uuid=%s elapsed=%.3fs label=%s conf=%.3f',
                                   self.uuid, elapsed_emb, emb_label, emb_conf)
                        self._responding = True
                        self._trigger_immediate_response(emb_label)
                        return
                    else:
                        logger.info("[EMB_CLF] low confidence %.3f, fallback to transfer (081)", emb_conf)
                        self._responding = True
                        self._trigger_immediate_response("081_transfer")
                        return
                except Exception as e:
                    logger.warning("[EMB_CLF] error: %s, fallback to transfer (081)", e)
                    self._responding = True
                    self._trigger_immediate_response("081_transfer")
                    return

            # --- Whisper text fallback ---
            # Run Whisper inference
            segments, info = self._model.transcribe(
                audio_16k,
                language="ja",
                initial_prompt="もしもし、こんにちは。料金について教えてください。導入を検討しています。担当者をお願いします。セキュリティは大丈夫ですか。24時間対応ですか。ホームページを見ました。",
                beam_size=3,
                best_of=1,
                vad_filter=False,
                without_timestamps=True,
                no_speech_threshold=None,
            )

            # Collect results
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            full_text = "".join(text_parts).strip()
            elapsed = time.time() - start_time
            
            # システム音声の誤認識をフィルタリング
            SYSTEM_NOISE = ["ご視聴", "チャンネル登録", "お客様に", "お客様の"]
            if any(noise in full_text for noise in SYSTEM_NOISE):
                logger.info("[WHISPER] filtered system noise: '%s'", full_text)
                return

            logger.info('[WHISPER] result uuid=%s elapsed=%.3fs text="%s"',
                       self.uuid, elapsed, full_text)

            if full_text:
                # Log ASR result
                if hasattr(self, 'call_logger') and self.call_logger:
                    is_final = not interim
                    self.call_logger.log_asr(full_text, is_final, 0.0)

                # Process result with StreamingLLMHandler
                if self._streaming_llm:
                    if interim:
                        # For interim results, add fragment to streaming LLM
                        self._streaming_llm.add_fragment(full_text)
                        logger.info("[WHISPER] interim fragment sent to streaming LLM: %r", full_text)
                    else:
                        # For final results, add fragment first then get best candidate
                        self._streaming_llm.add_fragment(full_text)
                        logger.info("[WHISPER] final fragment sent to streaming LLM: %r", full_text)
                        response_id = self._streaming_llm.finalize()
                        if response_id:
                            logger.info("[WHISPER] streaming LLM final response: %s", response_id)
                            # Trigger immediate response with the selected ID
                            self._trigger_immediate_response(response_id)
                        else:
                            # Fallback to traditional processing
                            self._append_transcript(True, full_text, 0.0)
                else:
                    # Fallback to traditional processing
                    if interim:
                        self._append_transcript(False, full_text, 0.0)
                    else:
                        self._append_transcript(True, full_text, 0.0)

        except Exception as e:
            logger.error("[WHISPER] transcription error uuid=%s err=%s", self.uuid, e)

    def _resample_8k_to_16k(self, pcm_data):
        """8kHz 16-bit PCM -> 16kHz float32 numpy array for Whisper"""
        # Decode 16-bit PCM
        samples_8k = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
        # DEBUG: save raw PCM before any processing
        try:
            import wave as _wave
            _raw_path = f"/tmp/whisper_raw_{int(time.time())}.wav"
            _raw_int16 = np.frombuffer(pcm_data, dtype=np.int16)
            with _wave.open(_raw_path, "w") as _wf:
                _wf.setnchannels(1)
                _wf.setsampwidth(2)
                _wf.setframerate(8000)
                _wf.writeframes(_raw_int16.tobytes())
            logger.info("[DEBUG_RAW] saved %s (%d samples)", _raw_path, len(_raw_int16))
        except: pass
        
        # WebSocket audio is already mono
        samples_8k_mono = samples_8k
        
        # Normalize to [-1, 1] range (fixed scale, same as offline)
        samples_8k_normalized = samples_8k_mono / 32768.0
        
        # Amplification DISABLED - causes hallucination at higher RMS
        rms = np.sqrt(np.mean(samples_8k_normalized ** 2))
        logger.info("[WHISPER] audio rms=%.4f (no amplification)", rms)
        
        # Simple linear interpolation for 8k -> 16k
        n = len(samples_8k_normalized)
        indices_16k = np.arange(0, n, 0.5)
        indices_16k = indices_16k[indices_16k < n]
        samples_16k = np.interp(indices_16k, np.arange(n), samples_8k_normalized)


        # DEBUG: save resampled audio for inspection
        import wave as _wave
        _debug_path = f"/tmp/whisper_debug_{int(time.time())}.wav"
        try:
            _pcm16 = (samples_16k * 32767).astype(np.int16)
            with _wave.open(_debug_path, 'w') as _wf:
                _wf.setnchannels(1)
                _wf.setsampwidth(2)
                _wf.setframerate(16000)
                _wf.writeframes(_pcm16.tobytes())
            logger.info("[DEBUG_WAV] saved %s (%d samples)", _debug_path, len(_pcm16))
        except Exception as _e:
            logger.warning("[DEBUG_WAV] failed: %s", _e)

        return samples_16k.astype(np.float32)

    # Mapping: classifier label -> actual audio response
    _RESPONSE_MAP = {
        "099": "081",
        "0604": "125",
    }

    def _trigger_immediate_response(self, response_id):
        response_id = self._RESPONSE_MAP.get(response_id, response_id)
        """即時応答をトリガー - StreamingLLMHandlerからの候補IDで音声再生"""
        try:
            # 再生中はASRバッファをミュート（システム音声を拾わないため）
            self._muted = True
            self._audio_buffer = bytearray()
            if hasattr(self, 'silence_handler') and self.silence_handler:
                self.silence_handler.pause_timer()
            logger.info("[IMMEDIATE_RESP] muted for playback response_id=%s", response_id)
            
            # 再生完了後にunmuteするタイマー（音声長さに応じて調整）
            import wave as _wave
            audio_path_check = f"/opt/libertycall/clients/{self.client_id}/audio/{response_id}.wav"
            try:
                with _wave.open(audio_path_check) as wf:
                    duration = wf.getnframes() / wf.getframerate()
                unmute_delay = duration + 0.5  # 音声長 + 0.5秒マージン
            except:
                unmute_delay = 5.0  # デフォルト5秒
            
            def _unmute():
                self._muted = False
                self._responding = False
                # Reset silence timer after playback complete
                if hasattr(self, 'silence_handler') and self.silence_handler:
                    self.silence_handler.resume_timer()
                self._audio_buffer = bytearray()
                logger.info("[IMMEDIATE_RESP] unmuted after %.1fs", unmute_delay)
            
            threading.Timer(unmute_delay, _unmute).start()
            # 音声ファイルパスを構築
            audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/{response_id}.wav"
            
            if not os.path.exists(audio_path):
                logger.warning("[IMMEDIATE_RESP] audio file not found: %s", audio_path)
                return
            
            # 即時応答ログ
            logger.info("[IMMEDIATE_RESP] triggering response_id=%s uuid=%s", 
                       response_id, self.uuid)
            
            # JSONLに即時応答を記録
            if hasattr(self, 'call_logger') and self.call_logger:
                self.call_logger.log_response(response_id, [response_id], "IMMEDIATE")
            
            # ESL経由で音声再生
            if self._esl:
                cmd = f'uuid_broadcast {self.uuid} {audio_path} aleg'
                self._esl.api(cmd)
                logger.info("[IMMEDIATE_RESP] ESL playback command sent: %s", cmd)
            else:
                logger.warning("[IMMEDIATE_RESP] ESL not available for playback")
                
        except Exception as e:
            logger.error("[IMMEDIATE_RESP] error triggering response: %s", e)

    def _append_transcript(self, is_final, transcript, confidence):
        """音声認識結果を蓄積し、必要に応じて応答"""
        if not transcript or not transcript.strip():
            return
        
        cleaned = transcript.strip()
        logger.info("[ACCUMULATE] uuid=%s text=%r is_final=%s",
                    self.uuid, cleaned, is_final)
        
        if is_final:
            # interim+タイマーで既に応答済みなら、finalでは応答しない
            if hasattr(self, '_interim_responded') and self._interim_responded:
                logger.info("[SKIP_FINAL] uuid=%s already responded via interim, text=%r",
                           self.uuid, cleaned)
                self._interim_responded = False
                self._accumulated_text = ""
                self._responded_offset = 0
                self._extended_once = False
                if self._silence_timer:
                    self._silence_timer.cancel()
                return
            
            self._accumulated_text = cleaned
            self._responded_offset = 0
            self._extended_once = False
            if self._silence_timer:
                self._silence_timer.cancel()
            self._on_silence_timeout()

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
