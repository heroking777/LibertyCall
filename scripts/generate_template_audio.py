#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テンプレート110, 111, 112の音声ファイル生成スクリプト

使い方:
    python scripts/generate_template_audio.py

生成されるファイル:
    - clients/000/audio/template_110.wav
    - clients/000/audio/template_111.wav
    - clients/000/audio/template_112.wav

設定:
    - テンプレート定義は intent_rules.py から読み込む
    - Google Cloud Text-to-Speech を使用
    - 24kHz, LINEAR16, モノラル形式で生成
"""

import os
import sys
from pathlib import Path
from google.cloud import texttospeech
import wave

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# テンプレート定義をインポート
from gateway.common.text_utils import TEMPLATE_CONFIG

# 出力ディレクトリ
OUTPUT_DIR = PROJECT_ROOT / "clients" / "000" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 生成対象テンプレートID
TEMPLATE_IDS = ["110", "111", "112"]

# TTS設定（intent_rules.pyの設定に合わせる）
SAMPLE_RATE = 24000  # 24kHz（LibertyCallの標準）
LANGUAGE_CODE = "ja-JP"


def check_credentials():
    """Google Cloud認証情報の確認"""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        # 代替環境変数も確認
        if not os.getenv("LC_GOOGLE_CREDENTIALS_PATH"):
            print("エラー: GOOGLE_APPLICATION_CREDENTIALS または LC_GOOGLE_CREDENTIALS_PATH 環境変数が設定されていません。")
            print("GCPの認証JSONファイルのパスを設定してください。")
            print("例: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json")
            return False
        else:
            # LC_GOOGLE_CREDENTIALS_PATH を GOOGLE_APPLICATION_CREDENTIALS に設定
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("LC_GOOGLE_CREDENTIALS_PATH")
    return True


def generate_template_audio(template_id: str, text: str, voice_name: str, rate: float = 1.0):
    """
    テンプレート用の音声ファイルを生成
    
    Args:
        template_id: テンプレートID
        text: 音声化するテキスト
        voice_name: 音声モデル名
        rate: 音声速度（speaking_rate）
    
    Returns:
        成功した場合True
    """
    try:
        # クライアント初期化
        client = texttospeech.TextToSpeechClient()
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=LANGUAGE_CODE,
            name=voice_name,
        )
        
        # 音声設定（LINEAR16, 24kHz, モノラル）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=rate,
        )
        
        # 音声合成実行
        print(f"  [{template_id}] 音声生成中... (速度: {rate}x, モデル: {voice_name})")
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ファイルパス
        output_path = OUTPUT_DIR / f"template_{template_id}.wav"
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        file_size = output_path.stat().st_size
        duration_sec = len(response.audio_content) / 2 / SAMPLE_RATE  # PCM16なので2バイト/サンプル
        
        print(f"  [{template_id}] ✓ 生成完了: {output_path}")
        print(f"  [{template_id}]   ファイルサイズ: {file_size:,} bytes")
        print(f"  [{template_id}]   音声長: {duration_sec:.2f}秒")
        
        return True
        
    except Exception as e:
        print(f"  [{template_id}] ✗ エラー: 音声生成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("テンプレート音声ファイル生成スクリプト")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # 設定表示
    print(f"\n設定:")
    print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
    print(f"  出力形式: WAV (16bit, モノラル)")
    print(f"  出力先: {OUTPUT_DIR}")
    
    # テンプレート定義を確認
    print(f"\n生成対象テンプレート: {', '.join(TEMPLATE_IDS)}")
    
    success_count = 0
    fail_count = 0
    
    for template_id in TEMPLATE_IDS:
        if template_id not in TEMPLATE_CONFIG:
            print(f"\n[{template_id}] ✗ エラー: テンプレート定義が見つかりません")
            fail_count += 1
            continue
        
        config = TEMPLATE_CONFIG[template_id]
        text = config.get("text", "")
        voice_name = config.get("voice", "ja-JP-Neural2-B")
        rate = config.get("rate", 1.0)
        
        if not text:
            print(f"\n[{template_id}] ✗ エラー: テキストが設定されていません")
            fail_count += 1
            continue
        
        print(f"\n[{template_id}] テキスト: {text}")
        
        if generate_template_audio(template_id, text, voice_name, rate):
            success_count += 1
        else:
            fail_count += 1
    
    # 結果サマリー
    print("\n" + "=" * 60)
    print("生成結果サマリー")
    print("=" * 60)
    print(f"  成功: {success_count}件")
    print(f"  失敗: {fail_count}件")
    
    if success_count > 0:
        print(f"\n✓ 音声ファイルを生成しました")
        print(f"  出力先: {OUTPUT_DIR}")
        return 0
    else:
        print("\n✗ 音声ファイルの生成に失敗しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
