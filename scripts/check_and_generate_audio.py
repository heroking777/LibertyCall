#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""クライアント000の音声データを確認し、不足分を生成するスクリプト"""

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
        file_size = wav_file.stat().st_size
        print(f"✓ 既存: template_{template_id}.wav ({file_size:,} bytes)")

print("\n" + "=" * 60)
print("クライアント000 音声データ確認")
print("=" * 60)
print(f"\nvoice_lines_000.json のテンプレート数: {len(voice_lines_ids)}")
print(f"intent_rules.py TEMPLATE_CONFIG のテンプレート数: {len(template_config_ids)}")
print(f"既存音声ファイル: {len(existing_files)}件")

# 差分を確認
only_in_voice_lines = voice_lines_ids - template_config_ids
only_in_template_config = template_config_ids - voice_lines_ids

if only_in_voice_lines:
    print(f"\n⚠️ voice_lines_000.json のみに存在 ({len(only_in_voice_lines)}件): {sorted(only_in_voice_lines)}")
if only_in_template_config:
    print(f"\n⚠️ intent_rules.py のみに存在 ({len(only_in_template_config)}件): {sorted(only_in_template_config)}")

# 不足しているファイルを特定（intent_rules.pyのTEMPLATE_CONFIGを優先）
all_template_ids = template_config_ids  # intent_rules.pyを優先
missing_files = all_template_ids - existing_files

if not missing_files:
    print("\n✅ すべてのテンプレートに対応する音声ファイルが存在します")
    sys.exit(0)

print(f"\n⚠️ 不足している音声ファイル ({len(missing_files)}件):")
for tid in sorted(missing_files):
    config = TEMPLATE_CONFIG.get(tid, {})
    text = config.get('text', 'N/A')
    print(f"  - template_{tid}.wav: {text[:60]}...")

# 生成するか確認
print(f"\n不足している {len(missing_files)}件 の音声ファイルを生成しますか？")
print("生成を開始します...\n")

SAMPLE_RATE = 24000
LANGUAGE_CODE = "ja-JP"

success = 0
for template_id in sorted(missing_files):
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
print(f"生成完了: {success}/{len(missing_files)}件")
print("=" * 60)

if success == len(missing_files):
    print("\n✅ すべての音声ファイルが正常に生成されました")
    print(f"出力先: {OUTPUT_DIR}")
    sys.exit(0)
else:
    print(f"\n✗ エラー: {len(missing_files) - success}件のファイル生成に失敗しました")
    sys.exit(1)
