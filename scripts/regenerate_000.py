#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
000番音声ファイルのみ再生成スクリプト（男性ナチュラル、フォーマル）

使い方:
    python scripts/regenerate_000.py
"""

import os
import sys
import wave
from pathlib import Path
from google.cloud import texttospeech

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
AUDIO_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_FILE = AUDIO_DIR / "000.wav"

# TTS設定（男性ナチュラル、フォーマル）
SPEAKING_RATE = 1.0  # 音声速度
VOICE_NAME = "ja-JP-Neural2-D"  # 日本語男性 Neural2-D
LANGUAGE_CODE = "ja-JP"
SAMPLE_RATE = 44100  # サンプリングレート（Hz）

# 000番のテキスト
TEXT_000 = "品質向上のためこの通話は録音させていただきます。"


def check_credentials():
    """Google Cloud認証情報の確認"""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("エラー: GOOGLE_APPLICATION_CREDENTIALS 環境変数が設定されていません。")
        return False
    return True


def generate_audio():
    """000番の音声ファイルを生成"""
    try:
        # クライアント初期化
        client = texttospeech.TextToSpeechClient()
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=TEXT_000)
        
        # 音声選択パラメータ（男性ナチュラル）
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=VOICE_NAME,
        )
        
        # 音声設定（フォーマルな感じ）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=SPEAKING_RATE,
        )
        
        # 音声合成実行
        print(f"音声生成中... (モデル: {VOICE_NAME}, 速度: {SPEAKING_RATE}x)")
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(OUTPUT_FILE), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        print(f"✓ 000.wav 生成完了")
        print(f"  出力先: {OUTPUT_FILE}")
        print(f"  ファイルサイズ: {OUTPUT_FILE.stat().st_size:,} bytes")
        return True
        
    except Exception as e:
        print(f"✗ 000.wav 生成失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("000番音声ファイル再生成（男性ナチュラル、フォーマル）")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # 音声生成
    if generate_audio():
        print("\n" + "=" * 60)
        print("✔ 000.wav を男性ナチュラル音声（speaking_rate=1.0）で再生成しました")
        print("=" * 60)
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())











