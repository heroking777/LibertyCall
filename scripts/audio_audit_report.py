#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音声ファイル監査レポート生成スクリプト"""

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path("/opt/libertycall")
sys.path.insert(0, str(PROJECT_ROOT))

from gateway.common.text_utils import TEMPLATE_CONFIG

# voice_lines_000.jsonからテンプレートIDを取得
voice_lines_path = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"
with open(voice_lines_path, 'r', encoding='utf-8') as f:
    voice_lines = json.load(f)

# 音声ファイルの存在確認
audio_dir = PROJECT_ROOT / "clients" / "000" / "audio"
audio_dir.mkdir(parents=True, exist_ok=True)

voice_lines_ids = {k for k in voice_lines.keys() if k != 'voice'}
template_config_ids = set(TEMPLATE_CONFIG.keys())
common_ids = voice_lines_ids & template_config_ids

# 既存の音声ファイルを確認
existing_files = set()
if audio_dir.exists():
    for wav_file in audio_dir.glob("*.wav"):
        template_id = wav_file.stem.replace("template_", "")
        existing_files.add(template_id)

# レポート生成
print("=" * 80)
print("クライアント000 音声データ監査レポート")
print("=" * 80)

print(f"\n【統計】")
print(f"  voice_lines_000.json のテンプレート数: {len(voice_lines_ids)}")
print(f"  intent_rules.py TEMPLATE_CONFIG のテンプレート数: {len(template_config_ids)}")
print(f"  共通テンプレート数: {len(common_ids)}")
print(f"  既存音声ファイル数: {len(existing_files)}")

# 差分を確認
only_in_voice_lines = voice_lines_ids - template_config_ids
only_in_template_config = template_config_ids - voice_lines_ids

if only_in_voice_lines:
    print(f"\n【差分】voice_lines_000.json のみに存在 ({len(only_in_voice_lines)}件):")
    for tid in sorted(only_in_voice_lines):
        text = voice_lines.get(tid, {}).get('text', 'N/A')
        print(f"  - {tid}: {text[:50]}...")

if only_in_template_config:
    print(f"\n【差分】intent_rules.py のみに存在 ({len(only_in_template_config)}件):")
    for tid in sorted(only_in_template_config):
        text = TEMPLATE_CONFIG.get(tid, {}).get('text', 'N/A')
        print(f"  - {tid}: {text[:50]}...")

# 不足しているファイル（intent_rules.pyのTEMPLATE_CONFIGを基準）
missing_files = template_config_ids - existing_files

if missing_files:
    print(f"\n【不足】音声ファイルが不足しているテンプレート ({len(missing_files)}件):")
    for tid in sorted(missing_files):
        config = TEMPLATE_CONFIG.get(tid, {})
        text = config.get('text', 'N/A')
        voice = config.get('voice', 'N/A')
        rate = config.get('rate', 'N/A')
        print(f"  - template_{tid}.wav")
        print(f"    テキスト: {text}")
        print(f"    音声: {voice}, rate: {rate}")
else:
    print(f"\n【結果】✅ すべてのテンプレートに対応する音声ファイルが存在します")

# 既存ファイル一覧
if existing_files:
    print(f"\n【既存】音声ファイル一覧 ({len(existing_files)}件):")
    for tid in sorted(existing_files):
        wav_file = audio_dir / f"template_{tid}.wav"
        if wav_file.exists():
            file_size = wav_file.stat().st_size
            print(f"  ✓ template_{tid}.wav ({file_size:,} bytes)")

print("\n" + "=" * 80)
