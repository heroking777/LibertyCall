import logging
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gateway import realtime_gateway


class DummyAICore:
    def __init__(self):
        self.tts_callback = None
        self.asr_provider = "google"
        self.tts_client = None
        self.voice_params = None
        self.audio_config = None

    def set_call_id(self, call_id):
        return None

    def reset_call(self, call_id):
        return None

    def on_new_audio(self, call_id, chunk):
        return None

    def process_dialogue(self, user_audio):
        return b"", False, None, None, None

    def check_for_transcript(self, call_id):
        return None


@pytest.fixture()
def gateway_instance(monkeypatch):
    monkeypatch.setattr(realtime_gateway, "AICore", lambda: DummyAICore())
    config = realtime_gateway.load_config("/opt/libertycall/config/gateway.yaml")
    gateway = realtime_gateway.RealtimeGateway(config)

    fake_paths = [
        Path("/opt/libertycall/clients/000/audio/000.wav"),
        Path("/opt/libertycall/clients/000/audio/001.wav"),
        Path("/opt/libertycall/clients/000/audio/002.wav"),
    ]

    gateway.audio_manager.play_incoming_sequence = lambda client_id: fake_paths
    gateway._load_wav_as_ulaw8k = lambda path: (path.stem.encode() or b"x") * 200
    gateway._generate_silence_ulaw = lambda duration: b"S" * int(duration * 8000)
    return gateway


def test_initial_sequence_runs_every_reset(gateway_instance, caplog):
    caplog.set_level(logging.INFO)
    expected_phrase = "silence(0.5s) -> 000 -> 001 -> 002"
    for _ in range(3):
        caplog.clear()
        gateway_instance._reset_call_state()
        gateway_instance._queue_initial_audio_sequence("000")

        queued_chunks = list(gateway_instance.tts_queue)
        assert queued_chunks, "TTS queue is empty after enqueue"
        assert queued_chunks[0].startswith(b"S"), "First chunk must be the leading silence"
        assert gateway_instance.initial_sequence_played is True

        order_logs = [
            record.message
            for record in caplog.records
            if "initial queue order" in record.message
        ]
        assert order_logs, "Expected order log not found"
        assert expected_phrase in order_logs[0], order_logs[0]

