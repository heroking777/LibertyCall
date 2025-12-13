#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
004.wav（もしもし）を生成するスクリプト
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_FILE = OUTPUT_DIR / "004.wav"

# 設定パラメータ（voice_lines_000.json の 004 の設定に合わせる）
TEXT = "もしもし。"
VOICE_NAME = "ja-JP-Neural2-B"
SPEAKING_RATE = 1.1
SAMPLE_RATE = 44100
LANGUAGE_CODE = "ja-JP"

# 認証情報の設定
CRED_FILE = PROJECT_ROOT / "key" / "google_tts.json"
if CRED_FILE.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(CRED_FILE)
    print(f"認証情報を設定しました: {CRED_FILE}")
else:
    print(f"警告: 認証情報ファイルが見つかりません: {CRED_FILE}")

def generate_audio():
    """音声ファイルを生成"""
    try:
        # クライアント初期化
        client = texttospeech.TextToSpeechClient()
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=TEXT)
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=VOICE_NAME,
        )
        
        # 音声設定
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=SPEAKING_RATE,
        )
        
        # 音声合成実行
        print(f"音声生成中...")
        print(f"  テキスト: {TEXT}")
        print(f"  音声: {VOICE_NAME}")
        print(f"  速度: {SPEAKING_RATE}x")
        print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(OUTPUT_FILE), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        print(f"\n✓ 音声ファイル生成完了: {OUTPUT_FILE}")
        print(f"  ファイルサイズ: {OUTPUT_FILE.stat().st_size} bytes")
        return True
        
    except Exception as e:
        print(f"\n✗ エラー: 音声生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("004.wav（もしもし）生成スクリプト")
    print("=" * 60)
    print()
    
    if generate_audio():
        print("\n" + "=" * 60)
        print("✔ 完了")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("✗ 失敗")
        print("=" * 60)
        sys.exit(1)

