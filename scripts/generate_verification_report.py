#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""検証結果をファイルに出力するスクリプト"""

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path("/opt/libertycall")
sys.path.insert(0, str(PROJECT_ROOT))

from libertycall.gateway.text_utils import TEMPLATE_CONFIG

# voice_lines_000.jsonを読み込み
with open(PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json", 'r', encoding='utf-8') as f:
    voice_lines = json.load(f)

# 音声ファイル確認
audio_dir = PROJECT_ROOT / "clients" / "000" / "audio"
audio_files = set()
if audio_dir.exists():
    for wav in audio_dir.glob('*.wav'):
        tid = wav.stem.replace('template_', '')
        audio_files.add(tid)

template_ids = set(TEMPLATE_CONFIG.keys())
voice_ids = {k for k in voice_lines.keys() if k != 'voice'}

# テキスト不一致
mismatches = {}
common_ids = template_ids & voice_ids
for tid in common_ids:
    template_text = TEMPLATE_CONFIG.get(tid, {}).get('text', '').strip()
    voice_text = voice_lines.get(tid, {}).get('text', '').strip()
    if template_text != voice_text:
        mismatches[tid] = (voice_text, template_text)

# 不足音声ファイル
missing = template_ids - audio_files

# 孤立音声ファイル
orphan = audio_files - template_ids

# レポート生成
report = []
report.append("=" * 80)
report.append("クライアント000 音声ファイルと音声リストの検証結果")
report.append("=" * 80)
report.append("")
report.append("📊 統計情報:")
report.append(f"  - intent_rules.py テンプレート数: {len(template_ids)}")
report.append(f"  - voice_lines_000.json テンプレート数: {len(voice_ids)}")
report.append(f"  - 音声ファイル数: {len(audio_files)}")
report.append(f"  - 共通テンプレート: {len(common_ids)}")
report.append("")

report.append(f"⚠️ テキスト不一致: {len(mismatches)}件")
if mismatches:
    for tid in sorted(mismatches.keys()):
        old_text, new_text = mismatches[tid]
        report.append(f"  テンプレート {tid}:")
        report.append(f"    voice_lines_000.json: {old_text}")
        report.append(f"    intent_rules.py:      {new_text}")
report.append("")

report.append(f"⚠️ 不足音声ファイル: {len(missing)}件")
if missing:
    for tid in sorted(missing):
        text = TEMPLATE_CONFIG.get(tid, {}).get('text', 'N/A')
        report.append(f"  - template_{tid}.wav: {text}")
else:
    report.append("  ✅ すべてのテンプレートに対応する音声ファイルが存在します")
report.append("")

report.append(f"⚠️ 孤立音声ファイル: {len(orphan)}件")
if orphan:
    for tid in sorted(orphan):
        report.append(f"  - template_{tid}.wav")
else:
    report.append("  ✅ 孤立音声ファイルはありません")
report.append("")

report.append("=" * 80)

# ファイルに出力
output_file = PROJECT_ROOT / "logs" / "verification_report.txt"
output_file.parent.mkdir(parents=True, exist_ok=True)
with open(output_file, 'w', encoding='utf-8') as f:
    f.write("\n".join(report))

print("\n".join(report))
print(f"\n✅ レポートを保存しました: {output_file}")
