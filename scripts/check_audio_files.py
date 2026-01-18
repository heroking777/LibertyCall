#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""クライアント000の音声データと音声リストを確認するスクリプト"""

import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/libertycall')
from gateway.common.text_utils import TEMPLATE_CONFIG

# voice_lines_000.jsonからテンプレートIDを取得
voice_lines_path = Path("/opt/libertycall/clients/000/config/voice_lines_000.json")
with open(voice_lines_path, 'r', encoding='utf-8') as f:
    voice_lines = json.load(f)

# 音声ファイルの存在確認
audio_dir = Path("/opt/libertycall/clients/000/audio")
audio_dir.mkdir(parents=True, exist_ok=True)

voice_lines_ids = {k for k in voice_lines.keys() if k != 'voice'}
template_config_ids = set(TEMPLATE_CONFIG.keys())

print("=" * 60)
print("クライアント000 音声データ確認")
print("=" * 60)

print(f"\nvoice_lines_000.json のテンプレート数: {len(voice_lines_ids)}")
print(f"intent_rules.py TEMPLATE_CONFIG のテンプレート数: {len(template_config_ids)}")

# 差分を確認
only_in_voice_lines = voice_lines_ids - template_config_ids
only_in_template_config = template_config_ids - voice_lines_ids
common_ids = voice_lines_ids & template_config_ids

print(f"\n共通テンプレート: {len(common_ids)}件")
if only_in_voice_lines:
    print(f"\n⚠️ voice_lines_000.json のみに存在 ({len(only_in_voice_lines)}件):")
    for tid in sorted(only_in_voice_lines):
        text = voice_lines.get(tid, {}).get('text', 'N/A')
        print(f"  - {tid}: {text[:60]}...")
if only_in_template_config:
    print(f"\n⚠️ intent_rules.py のみに存在 ({len(only_in_template_config)}件):")
    for tid in sorted(only_in_template_config):
        text = TEMPLATE_CONFIG.get(tid, {}).get('text', 'N/A')
        print(f"  - {tid}: {text[:60]}...")

# 音声ファイルの存在確認
print(f"\n音声ファイル確認 (ディレクトリ: {audio_dir})")
existing_files = set()
if audio_dir.exists():
    for wav_file in audio_dir.glob("*.wav"):
        template_id = wav_file.stem.replace("template_", "")
        existing_files.add(template_id)
        file_size = wav_file.stat().st_size
        print(f"  ✓ {wav_file.name} ({file_size:,} bytes)")

if not existing_files:
    print("  ✗ 音声ファイルが見つかりません")

# 不足しているファイルを確認（共通テンプレートのみ）
missing_files = common_ids - existing_files
if missing_files:
    print(f"\n⚠️ 不足している音声ファイル ({len(missing_files)}件):")
    for tid in sorted(missing_files):
        text = TEMPLATE_CONFIG.get(tid, {}).get('text', voice_lines.get(tid, {}).get('text', 'N/A'))
        print(f"  - template_{tid}.wav: {text[:60]}...")
else:
    print(f"\n✅ すべての共通テンプレートに対応する音声ファイルが存在します")

# intent_rules.pyのみに存在するテンプレートも確認
if only_in_template_config:
    missing_template_only = only_in_template_config - existing_files
    if missing_template_only:
        print(f"\n⚠️ intent_rules.pyのみに存在するテンプレートの音声ファイル ({len(missing_template_only)}件):")
        for tid in sorted(missing_template_only):
            text = TEMPLATE_CONFIG.get(tid, {}).get('text', 'N/A')
            print(f"  - template_{tid}.wav: {text[:60]}...")

print("\n" + "=" * 60)
print("確認完了")
print("=" * 60)
