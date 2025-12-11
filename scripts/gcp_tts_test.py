#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Cloud TTS 速度確認用テスト音声生成スクリプト

使い方:
    python scripts/gcp_tts_test.py

生成されるファイル:
    - clients/000/audio/test_google_tts.wav

設定:
    - SPEED: 音声速度（初期値: 1.0）
    - VOICE_NAME: 音声モデル（ja-JP-Neural2-B または ja-JP-Neural2-C）
    - SAMPLE_RATE: サンプリングレート（44100Hz）
    - OUTPUT_FORMAT: WAV形式（16bit）

依存パッケージ:
    - google-cloud-texttospeech: pip install google-cloud-texttospeech
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_FILE = OUTPUT_DIR / "test_google_tts.wav"

# 設定パラメータ
SPEED = 1.1  # 音声速度（変更可能）
VOICE_NAME = "ja-JP-Neural2-B"  # 日本語女性 Neural2-B（または ja-JP-Neural2-C）
SAMPLE_RATE = 44100  # サンプリングレート（Hz）
LANGUAGE_CODE = "ja-JP"

# テスト音声テキスト（長め）
TEST_TEXT = """ありがとうございます。こちらはリバティーコールです。
現在、Google Cloud Text-to-Speech の Neural2 モデルを使って音声テストを行っています。
この音声は、速度や音質を確認するために生成されています。
聞き取りやすさ、声の自然さ、抑揚、速度などに問題がないかを確認してください。
必要に応じて速度を変更して、改めて別の音源を生成することも可能です。
以上、速度確認用のテスト音声でした。"""


def check_credentials():
    """Google Cloud認証情報の確認"""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("エラー: GOOGLE_APPLICATION_CREDENTIALS 環境変数が設定されていません。")
        print("GCPの認証JSONファイルのパスを設定してください。")
        print("例: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json")
        return False
    return True


def generate_tts_audio(text: str, output_path: Path, speed: float = 1.0):
    """
    Google Cloud TTSで音声を生成
    
    Args:
        text: 音声化するテキスト
        output_path: 出力ファイルパス
        speed: 音声速度（speaking_rate）
    
    Returns:
        成功した場合True
    """
    try:
        # クライアント初期化
        client = texttospeech.TextToSpeechClient()
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # 音声選択パラメータ（Neural2-J 日本語女性）
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=VOICE_NAME,
        )
        
        # 音声設定（WAV形式、16bit、44100Hz、モノラル）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=speed,
        )
        
        # 音声合成実行
        print(f"音声生成中... (速度: {speed}x, モデル: {VOICE_NAME})")
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        return True
        
    except Exception as e:
        print(f"エラー: 音声生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("Google Cloud TTS 速度確認用テスト音声生成")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # 設定表示
    print(f"\n設定:")
    print(f"  音声モデル: {VOICE_NAME}")
    print(f"  音声速度: {SPEED}x")
    print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
    print(f"  出力形式: WAV (16bit, モノラル)")
    print(f"  出力先: {OUTPUT_FILE}")
    
    # 音声生成
    print(f"\nテキスト長: {len(TEST_TEXT)}文字")
    if generate_tts_audio(TEST_TEXT, OUTPUT_FILE, speed=SPEED):
        print("\n" + "=" * 60)
        print("✓ 音声ファイルを生成しました")
        print("=" * 60)
        print(f"\n→ {OUTPUT_FILE}")
        print(f"\nファイルサイズ: {OUTPUT_FILE.stat().st_size:,} bytes")
        return 0
    else:
        print("\nエラー: 音声ファイルの生成に失敗しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())

