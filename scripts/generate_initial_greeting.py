#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クライアント000の初回挨拶シーケンス(000-002)をGoogle Cloud TTSで再生成するスクリプト

要件:
    - 000.wav : 男声 / ナチュラル / 1.0x
    - 001.wav : 女声 / ナチュラル / 1.1x
    - 002.wav : 女声 / ナチュラル / 1.1x

使い方:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
    python scripts/generate_initial_greeting.py
"""

import audioop
import os
import wave
from pathlib import Path
from typing import Dict, Tuple, Optional

from google.cloud import texttospeech

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

INITIAL_LINES: Dict[str, Dict[str, str]] = {
    "000": {
        "text": "品質向上のためこの通話は録音させていただきます。",
        "voice": "ja-JP-Neural2-D",  # 男声
        "rate": 1.0,
    },
    "001": {
        "text": "お電話ありがとうございます。",
        "voice": "ja-JP-Neural2-B",  # 女声（ドキュメント上 Female）
        "rate": 1.1,
    },
    "002": {
        "text": "リバティーコールでございます。",
        "voice": "ja-JP-Neural2-B",  # 女声（存在確認済み）
        "rate": 1.1,
    },
}

SAMPLE_RATE = 44100
SILENCE_DURATION_SEC = 0.5
SILENCE_SAMPLE_RATE = 8000
SILENCE_SAMPLES_8K = int(SILENCE_SAMPLE_RATE * SILENCE_DURATION_SEC)
SILENCE_FRAME_BYTES = b"\x00\x00" * SILENCE_SAMPLES_8K


def synthesize_to_wav(
    client: texttospeech.TextToSpeechClient,
    audio_id: str,
    config: Dict[str, str],
    *,
    output_dir: Path,
) -> Tuple[Path, float]:
    text = config["text"]
    voice_name = config["voice"]
    speaking_rate = config["rate"]

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="ja-JP",
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=SAMPLE_RATE,
        speaking_rate=speaking_rate,
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice_params,
        audio_config=audio_config,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{audio_id}.wav"
    audio_bytes = response.audio_content

    if audio_id == "000":
        if SAMPLE_RATE == SILENCE_SAMPLE_RATE:
            silence_bytes = SILENCE_FRAME_BYTES
        else:
            silence_bytes, _ = audioop.ratecv(
                SILENCE_FRAME_BYTES,
                2,
                1,
                SILENCE_SAMPLE_RATE,
                SAMPLE_RATE,
                None,
            )
        audio_bytes = silence_bytes + audio_bytes

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)

    duration_sec = len(audio_bytes) / 2 / SAMPLE_RATE

    return output_path, duration_sec


def regenerate_initial_greeting(
    client: Optional[texttospeech.TextToSpeechClient] = None,
    *,
    output_dir: Path = AUDIO_DIR,
) -> Tuple[int, Dict[str, Tuple[Path, float]]]:
    """TTSクライアントを差し替え可能にして再生成を実行する。"""
    client = client or texttospeech.TextToSpeechClient()
    results: Dict[str, Tuple[Path, float]] = {}
    for audio_id, cfg in INITIAL_LINES.items():
        path, duration = synthesize_to_wav(client, audio_id, cfg, output_dir=output_dir)
        results[audio_id] = (path, duration)
        extra = " prepended_silence=0.5s" if audio_id == "000" else ""
        print(
            f"[OK] {audio_id}.wav regenerated -> {path} voice={cfg['voice']} rate={cfg['rate']} duration={duration:.3f}s{extra}"
        )
    print("初回挨拶シーケンス(000-002)を再生成しました。")
    return 0, results


def main() -> int:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("ERROR: GOOGLE_APPLICATION_CREDENTIALS が設定されていません。")
        return 1

    status, _ = regenerate_initial_greeting()
    return status


if __name__ == "__main__":
    raise SystemExit(main())

