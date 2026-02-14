import json
import logging
import os
import struct
import sys
import threading
import time

logger = logging.getLogger(__name__)


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
        self._dialogue_config = None
        self._load_dialogue_config()

    def _load_dialogue_config(self):
        config_path = f"/opt/libertycall/clients/{self.client_id}/config/dialogue_config.json"
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._dialogue_config = json.load(f)
            logger.info("[SILENCE] dialogue_config loaded uuid=%s", self.uuid)
        except Exception as e:
            logger.error("[SILENCE] config load error: %s", e)
            self._dialogue_config = {
                'timeout_sequence': [
                    {"audio": "003", "delay": 10},
                    {"audio": "003", "delay": 10},
                    {"audio": "003", "delay": 10}
                ],
                'greeting_sequence': [{"audio": "000", "delay": 2}]
            }

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
        logger.info("[SILENCE] _play_audio called uuid=%s file=%s", self.uuid, filename)
        if not self.esl or not self.esl.connected():
            logger.warning("[SILENCE] ESL not connected uuid=%s", self.uuid)
            return False
        logger.info("[SILENCE] ESL connected, checking uuid_exists uuid=%s", self.uuid)
        check_result = self.esl.api(f"uuid_exists {self.uuid}")
        logger.info("[SILENCE] uuid_exists result=%s uuid=%s",
                     check_result.getBody() if check_result else "None", self.uuid)
        if not check_result or "-ERR" in str(check_result.getBody()) or "false" in str(check_result.getBody()).lower():
            logger.warning("[SILENCE] UUID no longer exists uuid=%s", self.uuid)
            self.is_running = False
            return False
        audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/{filename}"
        cmd = f"uuid_broadcast {self.uuid} {audio_path} aleg"
        logger.info("[SILENCE] broadcasting uuid=%s cmd=%s", self.uuid, cmd)
        try:
            result = self.esl.api(cmd)
            logger.info("[SILENCE] play uuid=%s file=%s result=%s",
                         self.uuid, filename, result.getBody() if result else "None")
            if result and result.getBody().startswith('+OK'):
                try:
                    flag_path = f"/tmp/asr_response_{self.uuid}.flag"
                    with open(flag_path, 'w') as f:
                        f.write(str(time.time()))
                    logger.info("[ASR_FLAG] Created: %s", flag_path)
                except Exception as e:
                    logger.warning("[ASR_FLAG] Failed to create: %s", e)
            return True
        except Exception as e:
            logger.error("[SILENCE] play error uuid=%s err=%s", self.uuid, e)
            return False

    def _hangup(self):
        if not self.esl or not self.esl.connected():
            return
        try:
            result = self.esl.api(f"uuid_kill {self.uuid}")
            logger.info("[SILENCE] hangup uuid=%s result=%s",
                         self.uuid, result.getBody() if result else "None")
        except Exception as e:
            logger.error("[SILENCE] hangup error uuid=%s err=%s", self.uuid, e)

    def _timer_loop(self):
        timeout_seq = self._dialogue_config.get('timeout_sequence', [
            {"audio": "003", "delay": 10},
            {"audio": "003", "delay": 10},
            {"audio": "003", "delay": 10}
        ])
        while self.is_running:
            time.sleep(1)
            if self.last_speech_time is None:
                continue
            elapsed = time.time() - self.last_speech_time
            if self.prompt_count < len(timeout_seq):
                item = timeout_seq[self.prompt_count]
                if elapsed >= item.get('delay', 10):
                    logger.info("[SILENCE] prompt%d uuid=%s elapsed=%.1f",
                                 self.prompt_count + 1, self.uuid, elapsed)
                    self._play_audio(f"{item['audio']}.wav")
                    self.prompt_count += 1
                    self.last_speech_time = time.time()
            elif self.prompt_count >= len(timeout_seq):
                if self.prompt_count == len(timeout_seq):
                    try:
                        audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/prompt_003_8k.wav"
                        if os.path.exists(audio_path):
                            file_size = os.path.getsize(audio_path)
                            audio_duration = max((file_size - 44) / 16000, 0.5)
                            timeout_delay = 10 + audio_duration
                        else:
                            timeout_delay = 35
                    except Exception:
                        timeout_delay = 35
                    if elapsed >= timeout_delay:
                        logger.info("[SILENCE] timeout uuid=%s elapsed=%.1f", self.uuid, elapsed)
                        self._hangup()
                        self.is_running = False
                        self.prompt_count += 1
                        break
                else:
                    if elapsed >= 10:
                        logger.info("[SILENCE] timeout uuid=%s elapsed=%.1f", self.uuid, elapsed)
                        self._hangup()
                        self.is_running = False
                        break

    def reset_timer(self):
        self.last_speech_time = time.time()
        self.prompt_count = 0
        logger.info("[SILENCE] timer_reset uuid=%s", self.uuid)

    def pause_timer(self):
        self._paused_time = time.time()
        logger.info("[SILENCE] timer_pause uuid=%s", self.uuid)

    def resume_timer(self):
        if hasattr(self, '_paused_time') and self._paused_time:
            pause_duration = time.time() - self._paused_time
            self.last_speech_time += pause_duration
            logger.info("[SILENCE] timer_resume uuid=%s pause_duration=%.1fs",
                         self.uuid, pause_duration)
        self._paused_time = None

    def play_greeting(self, gasr_session=None):
        greeting_seq = self._dialogue_config.get('greeting_sequence',
                                                  [{"audio": "000", "delay": 2}])
        logger.info("[GREETING] waiting 1.2s for line stabilization uuid=%s", self.uuid)
        time.sleep(1.2)
        if self.esl and self.esl.connected():
            self.esl.events("plain", "CHANNEL_EXECUTE_COMPLETE")
        for item in greeting_seq:
            audio_file = f"{item['audio']}.wav"
            audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/{audio_file}"
            try:
                file_size = os.path.getsize(audio_path)
                fallback_duration = max((file_size - 44) / 16000, 0.5)
            except Exception:
                fallback_duration = 2.0
            self._play_audio(audio_file)
            logger.info("[GREETING] playing %s uuid=%s", audio_file, self.uuid)
            playback_done = False
            wait_start = time.time()
            timeout = fallback_duration + 5.0
            while time.time() - wait_start < timeout:
                if not self.esl or not self.esl.connected():
                    break
                event = self.esl.recvEventTimed(500)
                if event:
                    event_name = event.getHeader("Event-Name") or ""
                    event_uuid = event.getHeader("Unique-ID") or ""
                    app = event.getHeader("Application") or ""
                    if (event_name == "CHANNEL_EXECUTE_COMPLETE"
                            and event_uuid == self.uuid
                            and app in ("playback", "broadcast")):
                        logger.info("[GREETING] playback_complete %s uuid=%s elapsed=%.1fs",
                                     audio_file, self.uuid, time.time() - wait_start)
                        playback_done = True
                        break
            if not playback_done:
                remaining = fallback_duration - (time.time() - wait_start)
                if remaining > 0:
                    logger.warning("[GREETING] event timeout, sleeping %.1fs uuid=%s",
                                    remaining, self.uuid)
                    time.sleep(remaining)
        logger.info("[GREETING] all playback complete, unmuting uuid=%s", self.uuid)
        self._connect_esl()
        if gasr_session:
            gasr_session.unmute()
            # Set flag for WhisperSession to reset speaking state
            gasr_session._greeting_complete = True
        self.start_timer()

    def start_timer(self):
        self.last_speech_time = time.time()
        self.prompt_count = 0
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()
        logger.info("[SILENCE] timer_started uuid=%s", self.uuid)

    def stop(self):
        logger.info("[SILENCE] stop called uuid=%s", self.uuid)
        self.is_running = False

    def detect_silence(self, chunk):
        """音声チャンクの振幅を見て無音を検知"""
        try:
            samples = struct.unpack(f'<{len(chunk)//2}h', chunk)
            amplitude = sum(abs(s) for s in samples) / len(samples)
        except Exception:
            return

        SILENCE_THRESHOLD = 500
        SILENCE_DURATION = 0.5

        now = time.time()
        if amplitude < SILENCE_THRESHOLD:
            if not hasattr(self, '_silence_start') or self._silence_start is None:
                self._silence_start = now
            silence_duration = now - self._silence_start
            if silence_duration >= SILENCE_DURATION:
                self.trigger_interim_response()

    def trigger_interim_response(self, on_silence_timeout=None, is_speaking=False):
        """沈黙検出時のinterim応答"""
        if not is_speaking or self._silence_start is None:
            return
        silence_duration = time.time() - self._silence_start
        if silence_duration < 1.0:
            return
        if on_silence_timeout:
            on_silence_timeout()
        # is_speakingと_silence_startのリセットは呼び出し元で行う
