#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
デモ用AI音声ファイル生成スクリプト
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "lp" / "audio"
AUDIO_DIR = PROJECT_ROOT / "lp" / "audio"

# AI音声の定義
AI_VOICES = [
    {
        "file": "ai_voice_01.mp3",
        "text": "お電話ありがとうございます。こちらはAI受付のリバティコールでございます。本日はどのようなご用件でしょうか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    },
    {
        "file": "ai_voice_02.mp3",
        "text": "ありがとうございます。お名前をフルネームでお願いできますか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    },
    {
        "file": "ai_voice_03.mp3",
        "text": "山田太郎さまですね。ありがとうございます。ご希望の日にちはいつになりますか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    },
    {
        "file": "ai_voice_04.mp3",
        "text": "12月15日・午後のご予約ですね。お時間は何時ごろをご希望でしょうか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    },
    {
        "file": "ai_voice_05.mp3",
        "text": "かしこまりました。12月15日・15時のご予約でお取りします。ご希望のメニューや内容はございますか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    },
    {
        "file": "ai_voice_06.mp3",
        "text": "承知いたしました。確認いたしますので、少々お待ちくださいませ。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    },
    {
        "file": "ai_voice_07.mp3",
        "text": "ご予約をお取りできました。当日はお気をつけてお越しください。ありがとうございました。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.0,
        "pitch": -2.0
    }
]

SAMPLE_RATE = 24000
LANGUAGE_CODE = "ja-JP"

# 認証情報の設定
CRED_FILE = PROJECT_ROOT / "key" / "google_tts.json"
if CRED_FILE.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(CRED_FILE)
    print(f"認証情報を設定しました: {CRED_FILE}")
else:
    print(f"警告: 認証情報ファイルが見つかりません: {CRED_FILE}")

def generate_audio(voice_config: dict, client: texttospeech.TextToSpeechClient) -> bool:
    """音声ファイルを生成（MP3形式）"""
    try:
        output_file = AUDIO_DIR / voice_config["file"]
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=voice_config["text"])
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=voice_config["voice"],
        )
        
        # 音声設定（MP3形式、pitch調整）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=voice_config["rate"],
            pitch=voice_config["pitch"],
        )
        
        # 音声合成実行
        print(f"音声生成中... {voice_config['file']}")
        print(f"  テキスト: {voice_config['text'][:50]}...")
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        
        # MP3形式で保存
        with open(str(output_file), "wb") as f:
            f.write(response.audio_content)
        
        print(f"✓ 生成完了: {output_file}")
        print(f"  ファイルサイズ: {output_file.stat().st_size} bytes")
        return True
        
    except Exception as e:
        print(f"\n✗ エラー: {voice_config['file']} の生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("デモ用AI音声ファイル生成")
    print("=" * 60)
    
    # Google Cloud TTSクライアント初期化
    try:
        client = texttospeech.TextToSpeechClient()
    except Exception as e:
        print(f"\nエラー: Google Cloud TTSクライアントの初期化に失敗しました: {e}")
        sys.exit(1)
    
    # 音声ファイル生成
    success_count = 0
    for voice_config in AI_VOICES:
        if generate_audio(voice_config, client):
            success_count += 1
    
    print("\n" + "=" * 60)
    if success_count == len(AI_VOICES):
        print(f"✔ 完了 ({success_count}/{len(AI_VOICES)} 件)")
    else:
        print(f"✗ 一部失敗 ({success_count}/{len(AI_VOICES)} 件成功)")
    print("=" * 60)
    
    sys.exit(0 if success_count == len(AI_VOICES) else 1)

