#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新規テンプレート0605, 0606用AI音声ファイル生成スクリプト
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent.parent
AUDIO_DIR = PROJECT_ROOT / "clients" / "000" / "audio"

# 新規テンプレート用AI音声の定義
NEW_TEMPLATES = [
    {
        "template_id": "0605",
        "text": "ありがとうございます。当店の営業時間は、平日が朝10時から夜7時まで、土曜日は夕方5時まででございます。日曜・祝日はお休みをいただいております。",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.1,
        "pitch": 0.0
    },
    {
        "template_id": "0606", 
        "text": "承知いたしました。ご希望の日時はございますでしょうか？お客様のお名前とご連絡先をお伺いしてもよろしいでしょうか？",
        "voice": "ja-JP-Neural2-B",
        "rate": 1.1,
        "pitch": 0.0
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

def generate_audio(template_config: dict, client: texttospeech.TextToSpeechClient) -> bool:
    """音声ファイルを生成（WAV形式）"""
    try:
        output_file = AUDIO_DIR / f"{template_config['template_id']}.wav"
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=template_config["text"])
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=template_config["voice"],
        )
        
        # 音声設定（WAV形式）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=template_config["rate"],
            pitch=template_config["pitch"],
        )
        
        # 音声合成実行
        print(f"音声生成中... {template_config['template_id']}.wav")
        print(f"  テキスト: {template_config['text']}")
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        
        # WAV形式で保存
        with open(str(output_file), "wb") as f:
            f.write(response.audio_content)
        
        print(f"✓ 生成完了: {output_file}")
        print(f"  ファイルサイズ: {output_file.stat().st_size} bytes")
        return True
        
    except Exception as e:
        print(f"\n✗ エラー: {template_config['template_id']}.wav の生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("新規テンプレート0605, 0606用AI音声ファイル生成")
    print("=" * 60)
    
    # Google Cloud TTSクライアント初期化
    try:
        client = texttospeech.TextToSpeechClient()
    except Exception as e:
        print(f"\nエラー: Google Cloud TTSクライアントの初期化に失敗しました: {e}")
        print("認証情報を確認してください。")
        sys.exit(1)
    
    # 音声ファイル生成
    success_count = 0
    for template_config in NEW_TEMPLATES:
        if generate_audio(template_config, client):
            success_count += 1
    
    print("\n" + "=" * 60)
    if success_count == len(NEW_TEMPLATES):
        print(f"✔ 完了 ({success_count}/{len(NEW_TEMPLATES)} 件)")
    else:
        print(f"✗ 一部失敗 ({success_count}/{len(NEW_TEMPLATES)} 件成功)")
    print("=" * 60)
    
    sys.exit(0 if success_count == len(NEW_TEMPLATES) else 1)
