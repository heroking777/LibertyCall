#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クライアント000の音声ファイル（003〜104, 110〜119）をGoogle Cloud TTSで一括生成するスクリプト

要件:
    - 003〜104, 110〜119: 女声 / ナチュラル / 1.1x / 8kHz
    - 000〜002 は対象外（既存ファイルを保護）

使い方:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
    python scripts/generate_client_000_audio_partial.py
"""

import json
import os
import wave
from pathlib import Path
from typing import Dict, Tuple, Optional

from google.cloud import texttospeech

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"
AUDIO_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# 対象IDの範囲（000〜002は除外）
TARGET_IDS = set()
# 003〜104
for i in range(3, 105):
    TARGET_IDS.add(f"{i:03d}")
# 110〜119
for i in range(110, 120):
    TARGET_IDS.add(f"{i:03d}")

SAMPLE_RATE = 8000


def load_voice_lines(config_path: Path) -> Dict[str, Dict[str, any]]:
    """JSONファイルから音声設定を読み込む"""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def synthesize_to_wav(
    client: texttospeech.TextToSpeechClient,
    audio_id: str,
    config: Dict[str, any],
    *,
    output_dir: Path,
) -> Tuple[Path, float]:
    """Google Cloud TTSで音声を生成してWAVファイルに保存"""
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

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_bytes)

    duration_sec = len(audio_bytes) / 2 / SAMPLE_RATE

    return output_path, duration_sec


def generate_audio_files(
    client: Optional[texttospeech.TextToSpeechClient] = None,
    *,
    config_file: Path = CONFIG_FILE,
    output_dir: Path = AUDIO_DIR,
) -> Tuple[int, Dict[str, Tuple[Path, float]]]:
    """音声ファイルを一括生成する"""
    if not config_file.exists():
        print(f"ERROR: 設定ファイルが見つかりません: {config_file}")
        return 1, {}

    voice_lines = load_voice_lines(config_file)
    client = client or texttospeech.TextToSpeechClient()
    results: Dict[str, Tuple[Path, float]] = {}

    # 対象IDのみを処理（000〜002は除外）
    for audio_id in sorted(k for k in voice_lines.keys() if k != 'voice'):
        if audio_id not in TARGET_IDS:
            continue

        cfg = voice_lines[audio_id]
        path, duration = synthesize_to_wav(client, audio_id, cfg, output_dir=output_dir)
        results[audio_id] = (path, duration)
        print(
            f"[OK] {audio_id}.wav voice={cfg['voice']} rate={cfg['rate']} duration={duration:.3f}s"
        )

    print(f"音声ファイルを {len(results)} 件生成しました。")
    return 0, results


def main() -> int:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("ERROR: GOOGLE_APPLICATION_CREDENTIALS が設定されていません。")
        return 1

    status, _ = generate_audio_files()
    return status


if __name__ == "__main__":
    raise SystemExit(main())











