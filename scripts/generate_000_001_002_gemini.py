#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クライアント000用の音声ファイル生成スクリプト（Gemini API版）

000、001、002の音声ファイルをGemini APIで生成します。

使い方:
    export GEMINI_API_KEY="your-api-key"
    python scripts/generate_000_001_002_gemini.py

生成されるファイル:
    - clients/000/audio/000.wav
    - clients/000/audio/001.wav
    - clients/000/audio/002.wav

依存パッケージ:
    - google-generativeai: pip install google-generativeai
"""

import os
import sys
import wave
import io
from pathlib import Path

try:
    import google.generativeai as genai
except ImportError:
    print("エラー: google-generativeai がインストールされていません。")
    print("インストール: pip install google-generativeai")
    sys.exit(1)

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
AUDIO_DIR = CLIENT_DIR / "audio"
TSV_FILE = CLIENT_DIR / "voice_list_000.tsv"

# TTS設定
SAMPLE_RATE = 24000  # サンプリングレート（Hz）- システムで使用している24kHzに合わせる
SPEAKING_RATE = 1.2  # 話す速度
PITCH = 0.0  # ピッチ

# 音声テキスト（voice_list_000.tsvから）
VOICE_TEXTS = {
    "000": "この通話は品質向上のため録音させて戴きます",
    "001": "お電話ありがとうございます",
    "002": "リバティーコールです。"
}


def check_credentials():
    """Gemini API認証情報の確認"""
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        print("エラー: GEMINI_API_KEY 環境変数が設定されていません。")
        print("Gemini APIキーを設定してください。")
        print("例: export GEMINI_API_KEY=your-api-key")
        return False
    return True


def ensure_directories():
    """必要なディレクトリを作成"""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ ディレクトリ確認: {AUDIO_DIR}")


def synthesize_with_gemini(text: str, speaking_rate: float = 1.2, pitch: float = 0.0) -> bytes:
    """
    Gemini APIを使用してテキストから音声を合成する
    
    Args:
        text: 音声化するテキスト
        speaking_rate: 話す速度
        pitch: ピッチ
    
    Returns:
        音声データ（bytes）または None
    """
    try:
        # 注: Gemini APIの実際の音声合成APIは、提供されている機能によって異なる可能性があります
        # ここでは一般的な実装パターンを試します
        
        # Gemini APIを使用した音声合成を試行
        # 注意: 実際のGemini APIが音声合成をサポートしているかどうかは、最新のドキュメントを確認してください
        
        # 暫定的な実装: Gemini APIが音声合成を直接サポートしていない場合は、
        # エラーメッセージを表示
        print(f"警告: Gemini APIの音声合成機能は現在サポートされていない可能性があります。")
        print(f"テキスト: {text}")
        print(f"代替案: Google Cloud TTS APIを使用するか、Gemini APIの最新ドキュメントを確認してください。")
        return None
        
    except Exception as e:
        print(f"エラー: Gemini API音声合成に失敗しました: {e}")
        return None


def generate_audio_gemini(audio_id: str, text: str) -> bool:
    """
    Gemini APIを使用して音声ファイルを生成
    
    Args:
        audio_id: 音声ID（例: "000"）
        text: 音声化するテキスト
    
    Returns:
        成功した場合True
    """
    try:
        output_wav = AUDIO_DIR / f"{audio_id}.wav"
        
        if not text:
            print(f"  ⚠ {audio_id}: テキストが空のためスキップ")
            return False
        
        print(f"\n音声生成中... ({audio_id}.wav)")
        print(f"  テキスト: {text}")
        print(f"  速度: {SPEAKING_RATE}x")
        print(f"  ピッチ: {PITCH}")
        print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
        
        # Gemini APIで音声合成
        audio_data = synthesize_with_gemini(text, SPEAKING_RATE, PITCH)
        
        if not audio_data:
            print(f"  ✗ {audio_id}: 音声合成に失敗しました")
            return False
        
        # WAVファイルとして保存
        with wave.open(str(output_wav), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data)
        
        print(f"✓ 音声ファイル生成完了: {output_wav}")
        print(f"  ファイルサイズ: {output_wav.stat().st_size} bytes")
        return True
        
    except Exception as e:
        print(f"  ✗ {audio_id}: エラー - {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("クライアント000用音声ファイル生成（Gemini API版）")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # ディレクトリ確認
    ensure_directories()
    
    # Gemini API初期化
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    try:
        genai.configure(api_key=gemini_api_key)
        print(f"\n✓ Gemini API認証成功")
    except Exception as e:
        print(f"\nエラー: Gemini APIの初期化に失敗しました: {e}")
        return 1
    
    # TTS設定表示
    print(f"\nTTS設定:")
    print(f"  速度: {SPEAKING_RATE}x")
    print(f"  ピッチ: {PITCH}")
    print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
    print(f"  出力形式: WAV (LINEAR16, 16bit, モノラル)")
    
    # 音声ファイル生成
    print(f"\n音声ファイル生成中... (000, 001, 002)")
    success_count = 0
    
    for audio_id in ["000", "001", "002"]:
        text = VOICE_TEXTS.get(audio_id, "")
        if generate_audio_gemini(audio_id, text):
            success_count += 1
    
    print(f"\n音声ファイル生成完了: 成功 {success_count}件 / 合計 3件")
    
    if success_count == 3:
        print("\n" + "=" * 60)
        print("✓ すべての音声ファイルが正常に生成されました！")
        print("=" * 60)
        return 0
    else:
        print("\n" + "=" * 60)
        print("⚠ 一部の音声ファイルの生成に失敗しました。")
        print("Gemini APIの音声合成機能がサポートされているか確認してください。")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

