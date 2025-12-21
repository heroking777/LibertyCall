#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
無音警告用の音源ファイル（000-004.wav～000-006.wav）を生成するスクリプト

生成ファイル:
- 000-004.wav: 「もしもし、ご用件をお伺いします」
- 000-005.wav: 「聞こえてますか？」
- 000-006.wav: 「音声が認識できないため、切らせていただきます」
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"

# 設定パラメータ（既存の音源ファイルと統一）
VOICE_NAME = "ja-JP-Neural2-B"
SPEAKING_RATE = 1.1  # 既存の音源に合わせる
SAMPLE_RATE = 8000  # 8kHz（ユーザー要求）
LANGUAGE_CODE = "ja-JP"

# 無音警告用のテキストとファイル名のマッピング
AUDIO_CONFIGS = {
    "000-004": {
        "text": "もしもし、ご用件をお伺いします",
        "description": "5秒無音警告"
    },
    "000-005": {
        "text": "聞こえてますか？",
        "description": "15秒無音警告"
    },
    "000-006": {
        "text": "音声が認識できないため、切らせていただきます",
        "description": "25秒無音警告"
    }
}

# 認証情報の設定
CRED_FILE = PROJECT_ROOT / "key" / "google_tts.json"
if CRED_FILE.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(CRED_FILE)
    print(f"認証情報を設定しました: {CRED_FILE}")
else:
    # 環境変数からも確認
    cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_env and Path(cred_env).exists():
        print(f"認証情報を設定しました（環境変数）: {cred_env}")
    else:
        print(f"警告: 認証情報ファイルが見つかりません: {CRED_FILE}")
        print("環境変数 GOOGLE_APPLICATION_CREDENTIALS を確認してください")

def generate_audio(audio_id: str, text: str, description: str) -> bool:
    """音声ファイルを生成"""
    try:
        output_file = OUTPUT_DIR / f"{audio_id}.wav"
        
        # クライアント初期化
        client = texttospeech.TextToSpeechClient()
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=VOICE_NAME,
        )
        
        # 音声設定（PCM 16bit, mono, 8kHz）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=SPEAKING_RATE,
        )
        
        # 音声合成実行
        print(f"\n[{audio_id}] 音声生成中...")
        print(f"  説明: {description}")
        print(f"  テキスト: {text}")
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
        with wave.open(str(output_file), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        # ファイルサイズと長さを計算
        file_size = output_file.stat().st_size
        duration_sec = len(response.audio_content) / 2 / SAMPLE_RATE  # PCM16なので2バイト/サンプル
        
        print(f"  ✓ 音声ファイル生成完了: {output_file}")
        print(f"    ファイルサイズ: {file_size:,} bytes")
        print(f"    再生時間: {duration_sec:.2f}秒")
        
        return True
        
    except Exception as e:
        print(f"\n  ✗ [{audio_id}] エラー: 音声生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False

def set_file_permissions():
    """生成されたファイルの所有権とパーミッションを設定"""
    try:
        for audio_id in AUDIO_CONFIGS.keys():
            audio_file = OUTPUT_DIR / f"{audio_id}.wav"
            if audio_file.exists():
                # 所有権をroot:rootに設定（sudoが必要な場合がある）
                os.chmod(audio_file, 0o644)
                print(f"  ✓ パーミッション設定: {audio_file} (644)")
    except Exception as e:
        print(f"  警告: パーミッション設定に失敗: {e}")

def main():
    """メイン処理"""
    print("=" * 60)
    print("無音警告用音源ファイル生成スクリプト")
    print("=" * 60)
    print()
    print(f"出力ディレクトリ: {OUTPUT_DIR}")
    print(f"生成ファイル数: {len(AUDIO_CONFIGS)}")
    print()
    
    success_count = 0
    failed_count = 0
    
    for audio_id, config in AUDIO_CONFIGS.items():
        if generate_audio(audio_id, config["text"], config["description"]):
            success_count += 1
        else:
            failed_count += 1
    
    # パーミッション設定
    if success_count > 0:
        print("\n" + "-" * 60)
        print("ファイルパーミッション設定中...")
        set_file_permissions()
    
    # 結果サマリー
    print("\n" + "=" * 60)
    print("生成結果")
    print("=" * 60)
    print(f"  成功: {success_count} ファイル")
    print(f"  失敗: {failed_count} ファイル")
    
    if failed_count == 0:
        print("\n" + "=" * 60)
        print("✔ すべての音源ファイルの生成が完了しました")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("✗ 一部のファイルの生成に失敗しました")
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()

