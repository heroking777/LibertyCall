"""GoogleStreamingSession - core ASR session management."""
import json
import logging
import os
import queue
import struct
import sys
import threading
import time

from google.cloud import speech

from speech_client_manager import SpeechClientManager
from call_logger import CallLogger
from gasr_dialog_handler import GASRDialogHandlerMixin

sys.path.insert(0, '/opt/libertycall')
from libs.esl.ESL import ESLconnection

logger = logging.getLogger(__name__)

GASR_SAMPLE_RATE = int(os.environ.get("GASR_SAMPLE_RATE", "8000"))
GASR_LANGUAGE = os.environ.get("GASR_LANGUAGE", "ja-JP")
GASR_OUTPUT_DIR = os.environ.get("GASR_OUTPUT_DIR", "/tmp")


class GoogleStreamingSession(GASRDialogHandlerMixin):
    def __init__(self, uuid, client_id="000"):
        self.uuid = uuid or "unknown"
        self.client_id = client_id
        self.language = GASR_LANGUAGE
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
        self.client = speech.SpeechClient()

        # voice_mapを事前読み込み
        self._voice_map = self._load_voice_list()

        # dialogue_configを事前読み込み
        self._dialogue_config = self._load_dialogue_config()

        # ESL接続を事前に作成
        self._esl = None
        self._connect_esl()

        # クライアント設定からphrase hintsを構築
        phrase_hints = self._load_phrase_hints()
        self._instant_keywords = set(self._load_instant_keywords()) if self._load_instant_keywords() else set()
        logger.info("[GASR] instant_keywords loaded count=%d uuid=%s",
                   len(self._instant_keywords), self.uuid)

        speech_contexts = []
        if phrase_hints:
            speech_contexts = [speech.SpeechContext(phrases=phrase_hints, boost=5.0)]
            logger.info("[GASR] phrase_hints loaded count=%d boost=5.0 uuid=%s",
                       len(phrase_hints), self.uuid)

        self.streaming_config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language,
                enable_automatic_punctuation=False,
                speech_contexts=speech_contexts,
            ),
            interim_results=True,
            single_utterance=False,
        )
        logger.info("[GASR] session_open uuid=%s config=LINEAR16/%s/%s",
                    self.uuid, self.sample_rate, self.language)

    # ------------------------------------------------------------------ #
    #  Config loaders
    # ------------------------------------------------------------------ #
    def _load_dialogue_config(self):
        """Load and cache dialogue_config.json"""
        config_path = f"/opt/libertycall/clients/{self.client_id}/config/dialogue_config.json"
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info("[GASR] dialogue_config loaded uuid=%s", self.uuid)
            return config
        except Exception as e:
            logger.warning("[GASR] dialogue_config load failed uuid=%s err=%s",
                          self.uuid, e)
            return {}

    def _load_phrase_hints(self):
        """dialogue_config.jsonのkeywordsからphrase hintsを構築"""
        config = self._dialogue_config
        if not config:
            logger.warning("[GASR] phrase_hints config not available uuid=%s",
                          self.uuid)
            return []
        hints = set()
        for pattern in config.get("patterns", []):
            for kw in pattern.get("keywords", []):
                hints.add(kw)
        return list(hints)


    def _load_instant_keywords(self):
        """dialogue_config.jsonのinstant_keywordsから即応答キーワードを構築"""
        config = self._dialogue_config
        if not config:
            logger.warning("[GASR] instant_keywords config not available uuid=%s", self.uuid)
            return []
        return config.get('instant_keywords', [])
    def _load_voice_list(self):
        """voice_list_000.tsvを読み込んでID→文言のマッピングを返す"""
        if hasattr(self, '_voice_map'):
            return self._voice_map
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

        # unmute直後のバッファ済み古い音声を捨てる
        if hasattr(self, '_flush_until') and time.time() < self._flush_until:
            return

        # 最初のチャンク受信時刻を記録
        if not hasattr(self, '_first_audio_time'):
            self._first_audio_time = time.time()
            logger.info("[TIMING] first_audio_received uuid=%s time=%.3f",
                       self.uuid, self._first_audio_time)

        self.queue.put(chunk)

        # BARGE_IN検知（再生中の発話で再生停止）
        if self._is_playing:
            try:
                samples = struct.unpack(f'<{len(chunk)//2}h', chunk)
                amplitude = sum(abs(s) for s in samples) / len(samples)
                if amplitude > 3000:
                    if not hasattr(self, '_barge_in_count'):
                        self._barge_in_count = 0
                    self._barge_in_count += 1
                    if self._barge_in_count >= 3:
                        logger.info("[BARGE_IN] detected amplitude=%.0f count=%d uuid=%s",
                                   amplitude, self._barge_in_count, self.uuid)
                        self._stop_current_playback()
                        self._is_playing = False
                        self._barge_in_count = 0
                else:
                    self._barge_in_count = 0
            except Exception:
                pass

        # キューサイズを定期的にログ出力（100チャンク毎）
        if not hasattr(self, '_chunk_count'):
            self._chunk_count = 0
        self._chunk_count += 1
        if self._chunk_count % 100 == 0:
            qsize = self.queue.qsize()
            logger.info("[QUEUE] uuid=%s chunk_count=%d queue_size=%d",
                       self.uuid, self._chunk_count, qsize)

        # 自前無音検知（エラーを握りつぶす）
        try:
            self.silence_handler.detect_silence(chunk)
        except Exception as e:
            logger.warning("[SILENCE_DETECT] error uuid=%s err=%s", self.uuid, e)

    # ------------------------------------------------------------------ #
    #  Session lifecycle
    # ------------------------------------------------------------------ #
    def close(self):
        if not self._stop_requested.is_set():
            self._stop_requested.set()
            self.queue.put(None)
        self._closed.wait(timeout=5)

    def _request_generator(self):
        logger.info("[GASR] _request_generator started uuid=%s", self.uuid)
        while True:
            try:
                chunk = self.queue.get(timeout=1.0)  # 1秒タイムアウト
                logger.debug("[GASR] _request_generator got chunk uuid=%s size=%d", self.uuid, len(chunk) if chunk else 0)
                if chunk is None:
                    logger.info("[GASR] _request_generator received None, breaking uuid=%s", self.uuid)
                    break
                if not chunk:
                    continue
                yield speech.StreamingRecognizeRequest(audio_content=chunk)
            except queue.Empty:
                logger.debug("[GASR] _request_generator queue empty, continuing uuid=%s", self.uuid)
                continue

    def _consume_responses(self):
        logger.info("[GASR] _consume_responses started uuid=%s", self.uuid)
        try:
            responses = self.client.streaming_recognize(
                self.streaming_config, requests=self._request_generator())
            logger.info("[GASR] got responses iterator uuid=%s", self.uuid)
            for response in responses:
                self._handle_response(response)
        except Exception as exc:
            logger.exception("[GASR] error uuid=%s detail=%s", self.uuid, exc)
        finally:
            logger.info("[GASR] _consume_responses finished uuid=%s", self.uuid)
            self._closed.set()

    def _handle_response(self, response):
        recv_time = time.time()
        for result in response.results:
            if not result.alternatives:
                continue
            alt = result.alternatives[0]
            text = alt.transcript or ""
            tag = "final" if result.is_final else "interim"

            if not hasattr(self, '_utterance_start_time') or \
               self._utterance_start_time is None:
                self._utterance_start_time = recv_time

            latency = recv_time - self._utterance_start_time
            logger.info('[TIMING] transcript_%s uuid=%s latency=%.3fs text="%s"',
                       tag, self.uuid, latency, text)

            if not result.is_final:
                self._last_interim_text = text
            if result.is_final:
                self._utterance_start_time = None
                self._last_interim_text = ''

            self._append_transcript(result.is_final, text, alt.confidence)

            # Log ASR results to call_logger
            if hasattr(self, 'call_logger') and self.call_logger:
                self.call_logger.log_asr(text, result.is_final, alt.confidence)

    # ------------------------------------------------------------------ #
    #  Silence detection
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    #  ESL connection
    # ------------------------------------------------------------------ #
    def _connect_esl(self):
        """ESL接続を作成"""
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

    def unmute(self):
        self.muted = False
        self._unmute_time = time.time()
        # unmute後、最初の0.5秒分のバッファ済み音声を捨てるためのフラグ
        self._flush_until = self._unmute_time + 0.2
        logger.info("[GASR] unmuted uuid=%s flush_until=%.3f", self.uuid, self._flush_until)
        if not hasattr(self, '_stream_started'):
            self._stream_started = True
            self._thread = threading.Thread(
                target=self._consume_responses, daemon=True)
            self._thread.start()
            logger.info("[GASR] streaming_started_fallback uuid=%s", self.uuid)

    # ------------------------------------------------------------------ #
    #  Transcript accumulation
    # ------------------------------------------------------------------ #
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
        else:
            self._accumulated_text = cleaned
            # 即応答判定：キーワードが部分一致 かつ 未応答ならタイマー待ちなしで即応答
            if self._instant_keywords and not self._interim_responded:
                for kw in self._instant_keywords:
                    if kw in cleaned:
                        logger.info("[INSTANT_RESPONSE] uuid=%s text=%r matched_kw=%r",
                                   self.uuid, cleaned, kw)
                        if self._silence_timer:
                            self._silence_timer.cancel()
                        self._on_silence_timeout()
                        return
            self._start_silence_timer()
