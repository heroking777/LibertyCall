#!/usr/bin/env python3
"""voice_list_000.tsv に従って full.wav を分割するユーティリティ."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from pydub import AudioSegment, silence

CLIENT_ID = "000"
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / CLIENT_ID
TSV_FILE = CLIENT_DIR / "voice_list_000.tsv"
FULL_AUDIO = CLIENT_DIR / "audio" / "full.wav"
OUTPUT_DIR = CLIENT_DIR / "audio" / "split_full"

# サイレンス検出パラメータ（経験的に voice_list_000.tsv との件数一致を確認済み）
MIN_SILENCE_LEN_MS = 600
SILENCE_THRESHOLD_DB = -35
SEEK_STEP_MS = 5
PADDING_MS = 50  # セグメント前後に付与して切り取り余裕を確保


def load_voice_list(tsv_path: Path) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    with tsv_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            entries.append((parts[0].strip(), parts[1].strip()))
    return entries


def detect_segments(audio: AudioSegment) -> List[Tuple[int, int]]:
    raw_segments = silence.detect_nonsilent(
        audio,
        min_silence_len=MIN_SILENCE_LEN_MS,
        silence_thresh=SILENCE_THRESHOLD_DB,
        seek_step=SEEK_STEP_MS,
    )
    segments: List[Tuple[int, int]] = []
    duration_ms = len(audio)
    for start, end in raw_segments:
        adj_start = max(0, start - PADDING_MS)
        adj_end = min(duration_ms, end + PADDING_MS)
        if adj_end > adj_start:
            segments.append((adj_start, adj_end))
    return segments


def export_segments(audio: AudioSegment, entries: List[Tuple[str, str]]) -> None:
    segments = detect_segments(audio)
    if len(segments) != len(entries):
        raise RuntimeError(
            f"セグメント数が一致しません: 検出 {len(segments)} 件 / TSV {len(entries)} 件"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for (voice_id, text), (start, end) in zip(entries, segments):
        segment_audio = audio[start:end]
        out_path = OUTPUT_DIR / f"{voice_id}.wav"
        segment_audio.export(out_path, format="wav")
        print(f"✓ {voice_id}.wav ({(end - start)/1000:.2f}s) - {text}")


def main() -> int:
    if not TSV_FILE.exists():
        print(f"エラー: TSVが見つかりません: {TSV_FILE}")
        return 1
    if not FULL_AUDIO.exists():
        print(f"エラー: 音声ファイルが見つかりません: {FULL_AUDIO}")
        return 1

    entries = load_voice_list(TSV_FILE)
    if not entries:
        print("エラー: TSVに有効なエントリがありません")
        return 1

    print(f"TSVエントリ数: {len(entries)} 件")
    audio = AudioSegment.from_wav(FULL_AUDIO)
    print(f"音声長: {len(audio)/1000:.2f} 秒")

    try:
        export_segments(audio, entries)
    except RuntimeError as exc:
        print(f"失敗: {exc}")
        return 1

    print(f"出力先: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
