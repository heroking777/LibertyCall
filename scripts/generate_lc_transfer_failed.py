#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
転送失敗時の音声ファイル生成スクリプト

生成されるファイル:
    /var/lib/asterisk/sounds/ja/lc-transfer-failed.wav
"""

import os
import sys
import wave
from pathlib import Path
from google.cloud import texttospeech

# 出力先
OUTPUT_DIR = Path("/var/lib/asterisk/sounds/ja")
OUTPUT_FILE = OUTPUT_DIR / "lc-transfer-failed.wav"

# TTS設定
TEXT = "大変恐れ入ります。現在、担当者の回線が込み合っております。こちらから折り返しご連絡いたしますので、このまま続けてお名前とご連絡先をお話しください。お話しが終わりましたら、そのまま電話をお切りください。"
VOICE_NAME = "ja-JP-Neural2-B"
LANGUAGE_CODE = "ja-JP"
SAMPLE_RATE = 8000  # Asterisk用は8kHzが一般的
SPEAKING_RATE = 1.1

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
        
        # 音声設定（Asterisk用: 8kHz, LINEAR16, モノラル）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=SPEAKING_RATE,
        )
        
        # 音声合成実行
        print(f"音声生成中... (voice={VOICE_NAME}, rate={SPEAKING_RATE}, sample_rate={SAMPLE_RATE}Hz)")
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
        
        print(f"✓ 生成完了: {OUTPUT_FILE}")
        print(f"  ファイルサイズ: {OUTPUT_FILE.stat().st_size} bytes")
        return True
        
    except Exception as e:
        print(f"✗ エラー: 音声生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = generate_audio()
    sys.exit(0 if success else 1)

