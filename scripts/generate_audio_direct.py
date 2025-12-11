#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直接実行用の音声ファイル生成スクリプト"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

PROJECT_ROOT = Path("/opt/libertycall")
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

cred_file = PROJECT_ROOT / "key" / "google_tts.json"
if not cred_file.exists():
    print(f"エラー: 認証ファイルが見つかりません: {cred_file}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_file)
print(f"認証ファイル: {cred_file}")

TEMPLATES = {
    "110": {"text": "もしもし？お声が遠いようです。もう一度お願いします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "111": {"text": "お電話聞こえていますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "112": {"text": "お声が確認できませんので、このまま切らせていただきます。", "voice": "ja-JP-Neural2-B", "rate": 1.1}
}

SAMPLE_RATE = 24000
LANGUAGE_CODE = "ja-JP"

print("=" * 60)
print("無音検出用テンプレート音声ファイル生成")
print("=" * 60)
print(f"\n出力先: {OUTPUT_DIR}\n")

success = 0
for template_id, config in TEMPLATES.items():
    try:
        print(f"[{template_id}] テキスト: {config['text']}")
        print(f"[{template_id}] 音声生成中...")
        
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=config['text'])
        voice = texttospeech.VoiceSelectionParams(language_code=LANGUAGE_CODE, name=config['voice'])
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=config['rate']
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
        print(f"[{template_id}] ✗ エラー: {e}")
        import traceback
        traceback.print_exc()

print("=" * 60)
print(f"生成完了: {success}/{len(TEMPLATES)}件")
print("=" * 60)

if success == len(TEMPLATES):
    print("\n✅ すべての音声ファイルが正常に生成されました")
    print(f"出力先: {OUTPUT_DIR}")
    for template_id in TEMPLATES.keys():
        output_path = OUTPUT_DIR / f"template_{template_id}.wav"
        if output_path.exists():
            print(f"  - {output_path.name} ({output_path.stat().st_size:,} bytes)")
    sys.exit(0)
else:
    print(f"\n✗ エラー: {len(TEMPLATES) - success}件のファイル生成に失敗しました")
    sys.exit(1)
