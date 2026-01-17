#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""クライアント000の音声ファイルと音声リストの一致確認スクリプト"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path("/opt/libertycall")
sys.path.insert(0, str(PROJECT_ROOT))

from libertycall.gateway.common.text_utils import TEMPLATE_CONFIG

# voice_lines_000.jsonからテンプレートIDを取得
voice_lines_path = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"
with open(voice_lines_path, 'r', encoding='utf-8') as f:
    voice_lines = json.load(f)

# 音声ファイルの存在確認
audio_dir = PROJECT_ROOT / "clients" / "000" / "audio"
audio_dir.mkdir(parents=True, exist_ok=True)

voice_lines_ids = {k for k in voice_lines.keys() if k != 'voice'}
template_config_ids = set(TEMPLATE_CONFIG.keys())

print("=" * 80)
print("クライアント000 音声データと音声リストの一致確認")
print("=" * 80)

print(f"\n📊 統計情報:")
print(f"  - voice_lines_000.json のテンプレート数: {len(voice_lines_ids)}")
print(f"  - intent_rules.py TEMPLATE_CONFIG のテンプレート数: {len(template_config_ids)}")

# 差分を確認
only_in_voice_lines = voice_lines_ids - template_config_ids
only_in_template_config = template_config_ids - voice_lines_ids
common_ids = voice_lines_ids & template_config_ids

print(f"  - 共通テンプレート: {len(common_ids)}件")
print(f"  - voice_lines_000.json のみ: {len(only_in_voice_lines)}件")
print(f"  - intent_rules.py のみ: {len(only_in_template_config)}件")

# voice_lines_000.json のみに存在するテンプレート
if only_in_voice_lines:
    print(f"\n⚠️ voice_lines_000.json のみに存在するテンプレート ({len(only_in_voice_lines)}件):")
    for tid in sorted(only_in_voice_lines):
        text = voice_lines.get(tid, {}).get('text', 'N/A')
        print(f"  - {tid}: {text[:70]}...")

# intent_rules.py のみに存在するテンプレート
if only_in_template_config:
    print(f"\n⚠️ intent_rules.py のみに存在するテンプレート ({len(only_in_template_config)}件):")
    for tid in sorted(only_in_template_config):
        text = TEMPLATE_CONFIG.get(tid, {}).get('text', 'N/A')
        print(f"  - {tid}: {text[:70]}...")

# 共通テンプレートのテキスト不一致を確認
print(f"\n📝 共通テンプレートのテキスト不一致確認:")
text_mismatches = []
for tid in sorted(common_ids):
    voice_text = voice_lines.get(tid, {}).get('text', '').strip()
    template_text = TEMPLATE_CONFIG.get(tid, {}).get('text', '').strip()
    if voice_text != template_text:
        text_mismatches.append(tid)
        print(f"\n  ⚠️ テンプレート {tid}:")
        print(f"    voice_lines_000.json: {voice_text}")
        print(f"    intent_rules.py:      {template_text}")

if not text_mismatches:
    print("  ✅ すべての共通テンプレートのテキストが一致しています")

# 音声ファイルの存在確認
print(f"\n🎵 音声ファイル確認 (ディレクトリ: {audio_dir}):")
existing_files = set()
if audio_dir.exists():
    for wav_file in sorted(audio_dir.glob("*.wav")):
        template_id = wav_file.stem.replace("template_", "")
        existing_files.add(template_id)
        file_size = wav_file.stat().st_size
        print(f"  ✓ {wav_file.name} ({file_size:,} bytes)")

if not existing_files:
    print("  ✗ 音声ファイルが見つかりません")

# 不足しているファイルを確認（intent_rules.pyを優先）
print(f"\n📋 不足している音声ファイル確認:")
# intent_rules.pyの全テンプレートを基準にする
all_required_ids = template_config_ids
missing_files = all_required_ids - existing_files

if missing_files:
    print(f"  ⚠️ 不足している音声ファイル ({len(missing_files)}件):")
    for tid in sorted(missing_files):
        text = TEMPLATE_CONFIG.get(tid, {}).get('text', 'N/A')
        print(f"    - template_{tid}.wav: {text[:70]}...")
else:
    print(f"  ✅ intent_rules.pyのすべてのテンプレートに対応する音声ファイルが存在します")

# voice_lines_000.jsonのみに存在し、音声ファイルがあるもの
orphan_files = existing_files - all_required_ids
if orphan_files:
    print(f"\n⚠️ intent_rules.pyに存在しない音声ファイル ({len(orphan_files)}件):")
    for tid in sorted(orphan_files):
        print(f"    - template_{tid}.wav")

print("\n" + "=" * 80)
print("確認完了")
print("=" * 80)

# サマリー
print(f"\n📊 サマリー:")
print(f"  - テキスト不一致: {len(text_mismatches)}件")
print(f"  - 不足音声ファイル: {len(missing_files)}件")
print(f"  - 孤立音声ファイル: {len(orphan_files)}件")

if text_mismatches:
    print(f"\n⚠️ 注意: テンプレート {', '.join(sorted(text_mismatches))} のテキストが不一致です")
    print("   intent_rules.py が優先されるため、音声ファイルは intent_rules.py の内容で生成してください。")
