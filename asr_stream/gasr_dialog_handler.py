"""GoogleStreamingSession用 ダイアログ処理Mixin"""
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class GASRDialogHandlerMixin:
    """_start_silence_timer / _on_silence_timeout / _handle_dialog 等を提供するMixin"""

    def _start_silence_timer(self):
        if self._silence_timer:
            self._silence_timer.cancel()
        self._silence_timer = threading.Timer(0.7, self._on_silence_timeout)
        self._silence_timer.start()

    def _on_silence_timeout(self):
        if not self._accumulated_text:
            return
        full_text = self._accumulated_text.strip()
        last_responded = getattr(self, '_last_responded_text', '')
        if full_text == last_responded:
            logger.info("[SKIP_SAME] uuid=%s text=%r", self.uuid, full_text)
            self._accumulated_text = ""
            return
        offset = getattr(self, '_responded_offset', 0)
        if offset > len(full_text):
            offset = 0
            logger.info("[OFFSET_RESET] uuid=%s asr_text_shorter_than_offset", self.uuid)
        new_text = full_text[offset:]
        if new_text and not new_text[0].isspace() and offset > 0:
            space_idx = new_text.find(' ')
            if space_idx >= 0:
                new_text = new_text[space_idx:].strip()
            else:
                new_text = ''
        if not new_text:
            return
        logger.info("[DEBUG_ENTRY] uuid=%s new_text=%r offset=%d full=%r",
                    self.uuid, new_text, offset, full_text)
        if len(new_text) < 4 and not getattr(self, '_extended_once', False):
            self._extended_once = True
            self._silence_timer = threading.Timer(0.7, self._on_silence_timeout)
            self._silence_timer.start()
            logger.info("[EXTEND_WAIT] uuid=%s text=%r len=%d", self.uuid, new_text, len(new_text))
            return
        self._extended_once = False
        self._responded_offset = len(full_text)
        self._last_responded_text = full_text
        self._accumulated_text = ""
        logger.info("[OFFSET_UPDATE] uuid=%s offset=%d", self.uuid, self._responded_offset)
        logger.info("[SILENCE_RESPONSE] uuid=%s text=%r", self.uuid, new_text)
        if hasattr(self, 'silence_handler') and self.silence_handler:
            self.silence_handler.reset_timer()
        self._handle_dialog(new_text)

    def _stop_current_playback(self):
        try:
            if hasattr(self, '_esl') and self._esl and self._esl.connected():
                result = self._esl.api(f"uuid_break {self.uuid} all")
                logger.info("[INTERRUPT] uuid=%s result=%s",
                             self.uuid, result.getBody() if result else "None")
        except Exception as e:
            logger.warning("[INTERRUPT] error uuid=%s err=%s", self.uuid, e)

    def _handle_dialog(self, transcript):
        from gateway.dialogue.dialogue_flow import get_response, get_action
        logger.info("[DIALOG_START] uuid=%s transcript=%r", self.uuid, transcript)
        try:
            voice_map = self._voice_map
            audio_ids, phase, state = get_response(
                text=transcript,
                phase=self._current_phase,
                state=self._dialog_state,
                client_id=self.client_id
            )
            logger.info("[DIALOG_AFTER_RESPONSE] uuid=%s audio_ids=%s phase=%s",
                         self.uuid, audio_ids, phase)
            if hasattr(self, 'call_logger') and self.call_logger:
                self.call_logger.log_response(transcript, audio_ids, phase)
            self._current_phase = phase
            self._dialog_state = state
            config = self._dialogue_config
            if not config:
                config = {}
            logger.info('[RESPONSE] input="%s" -> audio=%s phase=%s',
                         transcript.replace('"', "'"), audio_ids, phase)
            if not self._esl or not self._esl.connected():
                logger.warning("[ESL] reconnecting uuid=%s", self.uuid)
                self._connect_esl()
            try:
                if self._esl and self._esl.connected():
                    if audio_ids:
                        self._stop_current_playback()
                        self._is_playing = True
                        self._playback_end_time = time.time()
                        if hasattr(self, 'silence_handler') and self.silence_handler:
                            self.silence_handler.pause_timer()
                        for audio_id in audio_ids:
                            template = str(audio_id).zfill(3)
                            audio_path_8k = f"/dev/shm/audio/{template}_8k.wav"
                            ram_audio_path = f"/dev/shm/audio/{template}.wav"
                            if os.path.exists(audio_path_8k):
                                audio_path = audio_path_8k
                            elif os.path.exists(ram_audio_path):
                                audio_path = ram_audio_path
                            else:
                                audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/{template}.wav"
                            try:
                                file_size = os.path.getsize(audio_path)
                                audio_duration = max((file_size - 44) / 16000, 0.5)
                            except Exception:
                                audio_duration = 2.0
                            logger.info("[DIALOG_PLAYING] uuid=%s template=%s path=%s duration=%.2fs",
                                         self.uuid, template, audio_path, audio_duration)
                            broadcast_start = time.time()
                            if hasattr(self, 'call_logger') and self.call_logger:
                                self.call_logger.log_playback_start(template, audio_path)
                            result = self._esl.api(
                                f"uuid_broadcast {self.uuid} {audio_path} aleg")
                            broadcast_end = time.time()
                            logger.info("[TIMING] uuid_broadcast uuid=%s duration=%.3fs",
                                         self.uuid, broadcast_end - broadcast_start)
                            phrase = voice_map.get(template, "???")
                            body = result.getBody() if result else "NO_RESULT"
                            status = "OK" if result and "+OK" in str(body) else "NG"
                            logger.info("[PLAY] %s.wav -> %s [%s] esl_result=%s",
                                         template, status, phrase, body)
                            self._playback_end_time += audio_duration
                        action = get_action(state)
                        if action == "hangup":
                            if hasattr(self, 'silence_handler') and self.silence_handler:
                                self.silence_handler.stop()
                                logger.info("[SILENCE] pre-emptive stop for hangup uuid=%s",
                                             self.uuid)
                        self._start_clear_playing_thread(audio_ids, action, config)
                        logger.info("[DIALOG_PLAY_STARTED] uuid=%s end_time=%.3f",
                                     self.uuid, self._playback_end_time)
                    else:
                        logger.info("[DIALOG_NO_AUDIO_IDS] uuid=%s", self.uuid)
                        self._stop_requested.set()
                        action = get_action(state)
                        if action:
                            logger.info("[DIALOG_ACTION] uuid=%s action=%s", self.uuid, action)
                            if hasattr(self, 'call_logger') and self.call_logger:
                                self.call_logger.log_action(action)
                            if action == "hangup":
                                if hasattr(self, 'silence_handler') and self.silence_handler:
                                    self.silence_handler.stop()
                                result = self._esl.api(f"uuid_kill {self.uuid}")
                                logger.info("[ACTION_HANGUP] uuid=%s result=%s",
                                             self.uuid, result.getBody() if result else "None")
                                return
                            elif action == "transfer":
                                transfer_number = config.get("transfer_number", "999")
                                caller_id = config.get("caller_id_number", "58304073")
                                self._esl.api(
                                    f"uuid_setvar {self.uuid} effective_caller_id_number {caller_id}")
                                self._esl.api(
                                    f"uuid_setvar {self.uuid} effective_caller_id_name LibertyCall")
                                result = self._esl.api(
                                    f"uuid_transfer {self.uuid} {transfer_number}")
                                logger.info("[ACTION_TRANSFER] uuid=%s to=%s caller_id=%s result=%s",
                                             self.uuid, transfer_number, caller_id,
                                             result.getBody() if result else "None")
                                if hasattr(self, 'silence_handler') and self.silence_handler:
                                    self.silence_handler.stop()
                                self._stop_requested.set()
                                return
                else:
                    logger.info("[DIALOG_NOT_CONNECTED] uuid=%s", self.uuid)
            except Exception as e:
                logger.error("[DIALOG_EXCEPTION] uuid=%s error=%s", self.uuid, e)
        except Exception as e:
            logger.error("[DIALOG] error uuid=%s err=%s", self.uuid, e)
            try:
                if hasattr(self, '_esl') and self._esl and self._esl.connected():
                    audio_path = f"/opt/libertycall/clients/{self.client_id}/audio/004.wav"
                    result = self._esl.api(
                        f"uuid_broadcast {self.uuid} {audio_path} aleg")
                    logger.info("[PLAY] uuid=%s template=004(fallback) result=%s",
                                 self.uuid, result.getBody() if result else "None")
            except Exception:
                pass

    def _start_clear_playing_thread(self, audio_ids, action, config):
        def _clear_playing():
            wait_time = self._playback_end_time - time.time()
            while wait_time > 0 and self._is_playing:
                time.sleep(0.1)
                wait_time = self._playback_end_time - time.time()
            self._is_playing = False
            self._is_speaking = False
            logger.info("[PLAY_END] uuid=%s", self.uuid)
            if hasattr(self, 'call_logger') and self.call_logger:
                for aid in audio_ids:
                    t = str(aid).zfill(3)
                    self.call_logger.log_playback_end(t, 0.0)
            self._last_responded_text = ""
            if hasattr(self, 'silence_handler') and self.silence_handler:
                self.silence_handler.reset_timer()
            if action:
                logger.info("[DIALOG_ACTION] uuid=%s action=%s", self.uuid, action)
                if hasattr(self, 'call_logger') and self.call_logger:
                    self.call_logger.log_action(action)
                if action == "hangup":
                    if hasattr(self, 'silence_handler') and self.silence_handler:
                        self.silence_handler.stop()
                    result = self._esl.api(f"uuid_kill {self.uuid}")
                    logger.info("[ACTION_HANGUP] uuid=%s result=%s",
                                 self.uuid, result.getBody() if result else "None")
                elif action == "transfer":
                    transfer_number = config.get("transfer_number", "999")
                    caller_id = config.get("caller_id_number", "58304073")
                    self._esl.api(
                        f"uuid_setvar {self.uuid} effective_caller_id_number {caller_id}")
                    self._esl.api(
                        f"uuid_setvar {self.uuid} effective_caller_id_name LibertyCall")
                    result = self._esl.api(
                        f"uuid_transfer {self.uuid} {transfer_number}")
                    logger.info("[ACTION_TRANSFER] uuid=%s to=%s caller_id=%s result=%s",
                                 self.uuid, transfer_number, caller_id,
                                 result.getBody() if result else "None")
                    if hasattr(self, 'silence_handler') and self.silence_handler:
                        self.silence_handler.stop()
                    self._stop_requested.set()
        threading.Thread(target=_clear_playing, daemon=True).start()
