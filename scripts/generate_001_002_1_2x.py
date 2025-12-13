#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
001.wavと002.wavを1.2xで再生成するスクリプト
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"

# 設定パラメータ
AUDIO_CONFIGS = {
    "001": {
        "text": "お電話ありがとうございます。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.2
    },
    "002": {
        "text": "リバティーコールでございます。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.2
    }
}

SAMPLE_RATE = 44100
LANGUAGE_CODE = "ja-JP"

# 認証情報の設定
CRED_FILE = PROJECT_ROOT / "key" / "google_tts.json"
if CRED_FILE.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(CRED_FILE)
    print(f"認証情報を設定しました: {CRED_FILE}")
else:
    print(f"警告: 認証情報ファイルが見つかりません: {CRED_FILE}")

def generate_audio(audio_id: str, config: dict):
    """音声ファイルを生成"""
    try:
        output_file = OUTPUT_DIR / f"{audio_id}.wav"
        
        # クライアント初期化
        client = texttospeech.TextToSpeechClient()
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=config["text"])
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=config["voice"],
        )
        
        # 音声設定
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=config["rate"],
        )
        
        # 音声合成実行
        print(f"\n音声生成中... ({audio_id}.wav)")
        print(f"  テキスト: {config['text']}")
        print(f"  音声: {config['voice']}")
        print(f"  速度: {config['rate']}x")
        print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(output_file), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        print(f"✓ 音声ファイル生成完了: {output_file}")
        print(f"  ファイルサイズ: {output_file.stat().st_size} bytes")
        return True
        
    except Exception as e:
        print(f"\n✗ エラー: {audio_id}.wav の生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("001.wav と 002.wav を 1.2x で再生成")
    print("=" * 60)
    
    success_count = 0
    for audio_id, config in AUDIO_CONFIGS.items():
        if generate_audio(audio_id, config):
            success_count += 1
    
    print("\n" + "=" * 60)
    if success_count == len(AUDIO_CONFIGS):
        print(f"✔ 完了 ({success_count}/{len(AUDIO_CONFIGS)} 件)")
    else:
        print(f"✗ 一部失敗 ({success_count}/{len(AUDIO_CONFIGS)} 件成功)")
    print("=" * 60)
    
    sys.exit(0 if success_count == len(AUDIO_CONFIGS) else 1)

