import sys
from types import SimpleNamespace

import pytest

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import generate_initial_greeting as gig


class FakeTTSClient:
    def __init__(self):
        self.calls = []

    def synthesize_speech(self, input, voice, audio_config):
        self.calls.append(
            {
                "text": input.text,
                "voice": voice.name,
                "rate": audio_config.speaking_rate,
            }
        )
        audio_content = b"\x00\x00" * gig.SAMPLE_RATE  # 1秒ぶん
        return SimpleNamespace(audio_content=audio_content)


def test_generate_initial_greeting_logs_voice_and_duration(tmp_path, capsys):
    client = FakeTTSClient()
    status, results = gig.regenerate_initial_greeting(client=client, output_dir=tmp_path)

    assert status == 0
    assert set(results.keys()) == {"000", "001", "002"}
    for path, duration in results.values():
        assert path.parent == tmp_path
        assert duration == pytest.approx(1.0, rel=0.01)
        assert path.exists()

    captured = capsys.readouterr()
    for audio_id, cfg in gig.INITIAL_LINES.items():
        assert f"{audio_id}.wav regenerated" in captured.out
        assert f"voice={cfg['voice']}" in captured.out
        assert f"rate={cfg['rate']}" in captured.out
    assert "duration=1.000s" in captured.out

    for call, cfg in zip(client.calls, gig.INITIAL_LINES.values()):
        assert call["voice"] == cfg["voice"]
        assert call["rate"] == cfg["rate"]

