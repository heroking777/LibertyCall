#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
無音検出用テンプレート110, 111, 112の音声ファイル生成スクリプト（簡易版）

使い方:
    python scripts/generate_no_input_audio.py

生成されるファイル:
    - clients/000/audio/template_110.wav
    - clients/000/audio/template_111.wav
    - clients/000/audio/template_112.wav
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# テンプレート定義（intent_rules.pyから）
TEMPLATES = {
    "110": {
        "text": "もしもし？お声が遠いようです。もう一度お願いします。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.1
    },
    "111": {
        "text": "お電話聞こえていますか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.1
    },
    "112": {
        "text": "お声が確認できませんので、このまま切らせていただきます。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.1
    }
}

SAMPLE_RATE = 24000
LANGUAGE_CODE = "ja-JP"


def check_credentials():
    """Google Cloud認証情報の確認"""
    # 認証ファイルのパスを確認
    cred_file = PROJECT_ROOT / "key" / "google_tts.json"
    if cred_file.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_file)
        print(f"認証ファイルを設定: {cred_file}")
        return True
    
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        if not os.getenv("LC_GOOGLE_CREDENTIALS_PATH"):
            print("エラー: GOOGLE_APPLICATION_CREDENTIALS または LC_GOOGLE_CREDENTIALS_PATH 環境変数が設定されていません。")
            print(f"認証ファイルが見つかりません: {cred_file}")
            return False
        else:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("LC_GOOGLE_CREDENTIALS_PATH")
    return True


def generate_audio(template_id: str, text: str, voice_name: str, rate: float):
    """音声ファイルを生成"""
    try:
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=rate,
        )
        
        print(f"[{template_id}] 音声生成中...")
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        output_path = OUTPUT_DIR / f"template_{template_id}.wav"
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        file_size = output_path.stat().st_size
        duration = len(response.audio_content) / 2 / SAMPLE_RATE
        print(f"✅ TTS生成完了: template_{template_id}.wav")
        print(f"[{template_id}]   サイズ: {file_size:,} bytes, 長さ: {duration:.2f}秒")
        return True
    except Exception as e:
        print(f"[{template_id}] ✗ エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("無音検出用テンプレート音声ファイル生成")
    print("=" * 60)
    
    if not check_credentials():
        return 1
    
    print(f"\n出力先: {OUTPUT_DIR}\n")
    
    success = 0
    for template_id, config in TEMPLATES.items():
        print(f"[{template_id}] テキスト: {config['text']}")
        if generate_audio(template_id, config['text'], config['voice'], config['rate']):
            success += 1
        print()
    
    print("=" * 60)
    print(f"生成完了: {success}/{len(TEMPLATES)}件")
    print("=" * 60)
    
    return 0 if success == len(TEMPLATES) else 1


if __name__ == "__main__":
    sys.exit(main())
