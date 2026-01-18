#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不足しているすべてのテンプレート音声ファイルを生成するスクリプト"""

import os
import sys
import json
from pathlib import Path
from google.cloud import texttospeech
import wave

PROJECT_ROOT = Path("/opt/libertycall")
sys.path.insert(0, str(PROJECT_ROOT))

from gateway.common.text_utils import TEMPLATE_CONFIG

# 認証ファイルを設定
cred_file = PROJECT_ROOT / "key" / "google_tts.json"
if not cred_file.exists():
    print(f"エラー: 認証ファイルが見つかりません: {cred_file}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_file)
print(f"認証ファイル: {cred_file}")

# voice_lines_000.jsonからテンプレートIDを取得
voice_lines_path = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"
with open(voice_lines_path, 'r', encoding='utf-8') as f:
    voice_lines = json.load(f)

# 音声ファイルの存在確認
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

voice_lines_ids = {k for k in voice_lines.keys() if k != 'voice'}
template_config_ids = set(TEMPLATE_CONFIG.keys())
common_ids = voice_lines_ids & template_config_ids

# 既存の音声ファイルを確認
existing_files = set()
if OUTPUT_DIR.exists():
    for wav_file in OUTPUT_DIR.glob("*.wav"):
        template_id = wav_file.stem.replace("template_", "")
        existing_files.add(template_id)

# 不足しているファイルを特定
missing_files = common_ids - existing_files

# intent_rules.pyのみに存在するテンプレートも追加
only_in_template_config = template_config_ids - voice_lines_ids
missing_template_only = only_in_template_config - existing_files

all_missing = missing_files | missing_template_only

SAMPLE_RATE = 24000
LANGUAGE_CODE = "ja-JP"

print("=" * 60)
print("不足音声ファイル生成スクリプト")
print("=" * 60)
print(f"\n既存音声ファイル: {len(existing_files)}件")
print(f"不足している音声ファイル: {len(all_missing)}件")

if not all_missing:
    print("\n✅ すべての音声ファイルが存在します")
    sys.exit(0)

print(f"\n生成対象テンプレート ({len(all_missing)}件):")
for tid in sorted(all_missing):
    config = TEMPLATE_CONFIG.get(tid) or voice_lines.get(tid, {})
    text = config.get('text', 'N/A')
    print(f"  - {tid}: {text[:50]}...")

print(f"\n出力先: {OUTPUT_DIR}\n")

success = 0
for template_id in sorted(all_missing):
    try:
        # テンプレート設定を取得（intent_rules.py優先）
        config = TEMPLATE_CONFIG.get(template_id) or voice_lines.get(template_id, {})
        text = config.get('text', '')
        voice_name = config.get('voice', 'ja-JP-Neural2-B')
        rate = config.get('rate', 1.1)
        
        if not text:
            print(f"[{template_id}] ✗ エラー: テキストが設定されていません")
            continue
        
        print(f"[{template_id}] テキスト: {text}")
        print(f"[{template_id}] 音声生成中...")
        
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code=LANGUAGE_CODE, name=voice_name)
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=rate
        )
        
        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        
        output_path = OUTPUT_DIR / f"template_{template_id}.wav"
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        file_size = output_path.stat().st_size
        duration = len(response.audio_content) / 2 / SAMPLE_RATE
        print(f"✅ TTS生成完了: template_{template_id}.wav")
        print(f"[{template_id}]   サイズ: {file_size:,} bytes, 長さ: {duration:.2f}秒\n")
        success += 1
    except Exception as e:
        print(f"[{template_id}] ✗ エラー: {e}\n")
        import traceback
        traceback.print_exc()

print("=" * 60)
print(f"生成完了: {success}/{len(all_missing)}件")
print("=" * 60)

if success == len(all_missing):
    print("\n✅ すべての音声ファイルが正常に生成されました")
    print(f"出力先: {OUTPUT_DIR}")
    sys.exit(0)
else:
    print(f"\n✗ エラー: {len(all_missing) - success}件のファイル生成に失敗しました")
    sys.exit(1)
