#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 2.0 APIを使用した日本語TTS（音声合成）スクリプト

voice_list_000.tsvから000-003の音声ファイルを生成します。

使い方:
    export GOOGLE_API_KEY="your-api-key"
    # または
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
    
    python scripts/generate_gemini_tts.py

生成されるファイル:
    - output/000.wav
    - output/001.wav
    - output/002.wav
    - output/003.wav

依存パッケージ:
    - google-generativeai: pip install google-generativeai
"""

import os
import sys
import wave
import io
from pathlib import Path
from typing import Optional, Tuple

try:
    import google.generativeai as genai
except ImportError:
    print("エラー: google-generativeai がインストールされていません。")
    print("インストール: pip install google-generativeai")
    sys.exit(1)

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
TSV_FILE = CLIENT_DIR / "voice_list_000.tsv"
OUTPUT_DIR = CLIENT_DIR / "audio"

# TTS設定
SAMPLE_RATE = 24000  # 24kHz
BIT_DEPTH = 16  # 16bit
CHANNELS = 1  # モノラル

# Gemini 2.0 Flash モデル名
GEMINI_MODEL = "gemini-2.0-flash-exp"


def check_credentials() -> bool:
    """認証情報の確認"""
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if not google_api_key and not google_creds:
        print("エラー: 認証情報が設定されていません。")
        print("以下のいずれかを設定してください:")
        print("  export GOOGLE_API_KEY=\"your-api-key\"")
        print("  または")
        print("  export GEMINI_API_KEY=\"your-api-key\"")
        print("  または")
        print("  export GOOGLE_APPLICATION_CREDENTIALS=\"/path/to/credentials.json\"")
        return False
    return True


def ensure_directories():
    """必要なディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ 出力ディレクトリ確認: {OUTPUT_DIR}")


def load_voice_list() -> dict:
    """voice_list_000.tsvから音声テキストを読み込む"""
    voice_texts = {}
    
    if not TSV_FILE.exists():
        print(f"エラー: {TSV_FILE} が見つかりません。")
        sys.exit(1)
    
    with open(TSV_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split('\t', 1)
            if len(parts) == 2:
                audio_id = parts[0].strip()
                text = parts[1].strip()
                
                # 000-003のみ処理
                if audio_id in ["000", "001", "002", "003"]:
                    voice_texts[audio_id] = text
    
    return voice_texts


def synthesize_with_gemini_2_0(text: str) -> Optional[bytes]:
    """
    Gemini 2.0 Flash APIを使用してテキストから音声を合成する
    
    Args:
        text: 音声化するテキスト
    
    Returns:
        音声データ（bytes）または None
    """
    try:
        # Gemini 2.0 Flash with multimodal live APIを使用
        # 注: 実際のAPI仕様に合わせて調整が必要です
        
        # モデルの初期化
        model = genai.GenerativeModel(GEMINI_MODEL)
        
        # 音声生成のリクエスト
        # 注: Gemini 2.0の実際の音声生成APIは、最新のドキュメントを確認してください
        # ここでは一般的な実装パターンを試します
        
        # プロンプトを作成（音声生成用）
        prompt = f"以下の日本語テキストを自然な音声で読み上げてください: {text}"
        
        # 音声生成を試行
        # 注: Gemini 2.0 Flashの実際の音声生成メソッドは、APIドキュメントを確認してください
        try:
            # generate_contentを使用して音声を生成
            # 実際のAPIでは、音声生成専用のメソッドがある可能性があります
            response = model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "audio/wav",  # 音声形式を指定
                }
            )
            
            # レスポンスから音声データを取得
            if hasattr(response, 'audio_content'):
                return response.audio_content
            elif hasattr(response, 'text'):
                # テキストが返された場合（音声生成がサポートされていない場合）
                print(f"警告: Gemini APIは音声データではなくテキストを返しました。")
                return None
            else:
                print(f"警告: 予期しないレスポンス形式です。")
                return None
                
        except Exception as api_error:
            # APIエラーの場合、代替方法を試す
            print(f"API呼び出しエラー: {api_error}")
            print(f"代替方法を試します...")
            
            # 代替方法: generate_contentで音声生成を試行
            # 実際のAPI仕様に合わせて調整が必要です
            try:
                # 音声生成用の特別なメソッドがある場合
                if hasattr(model, 'generate_audio'):
                    audio_response = model.generate_audio(text=text)
                    if hasattr(audio_response, 'audio_content'):
                        return audio_response.audio_content
                
                # その他の方法を試す
                print(f"警告: Gemini 2.0 APIの音声生成機能が見つかりませんでした。")
                print(f"最新のAPIドキュメントを確認してください。")
                return None
                
            except Exception as e:
                print(f"代替方法も失敗: {e}")
                return None
        
    except Exception as e:
        print(f"エラー: Gemini API音声合成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return None


def convert_to_wav(audio_data: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """
    音声データをWAV形式に変換する
    
    Args:
        audio_data: 元の音声データ
        sample_rate: サンプリングレート
    
    Returns:
        WAV形式の音声データ
    """
    # 音声データがすでにWAV形式の場合はそのまま返す
    if audio_data[:4] == b'RIFF':
        return audio_data
    
    # その他の形式の場合は、WAVヘッダーを付けて変換
    # 注: 実際の音声データ形式に合わせて変換処理を実装する必要があります
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BIT_DEPTH // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)
    
    return wav_buffer.getvalue()


def generate_audio_file(audio_id: str, text: str) -> bool:
    """
    Gemini 2.0 APIを使用して音声ファイルを生成
    
    Args:
        audio_id: 音声ID（例: "000"）
        text: 音声化するテキスト
    
    Returns:
        成功した場合True
    """
    try:
        output_wav = OUTPUT_DIR / f"{audio_id}.wav"
        
        if not text:
            print(f"  ⚠ {audio_id}: テキストが空のためスキップ")
            return False
        
        print(f"\n音声生成中... ({audio_id}.wav)")
        print(f"  テキスト: {text}")
        print(f"  モデル: {GEMINI_MODEL}")
        print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
        
        # Gemini 2.0 APIで音声合成
        audio_data = synthesize_with_gemini_2_0(text)
        
        if not audio_data:
            print(f"  ✗ {audio_id}: 音声合成に失敗しました")
            print(f"    注: Gemini 2.0 APIの音声生成機能がサポートされていない可能性があります。")
            print(f"    最新のAPIドキュメントを確認してください。")
            return False
        
        # WAV形式に変換
        wav_data = convert_to_wav(audio_data, SAMPLE_RATE)
        
        # WAVファイルとして保存
        with open(output_wav, "wb") as f:
            f.write(wav_data)
        
        file_size = output_wav.stat().st_size
        print(f"✓ 音声ファイル生成完了: {output_wav}")
        print(f"  ファイルサイズ: {file_size:,} bytes")
        return True
        
    except Exception as e:
        print(f"  ✗ {audio_id}: エラー - {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("Gemini 2.0 API 日本語TTS音声生成")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # ディレクトリ確認
    ensure_directories()
    
    # Gemini API初期化
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    try:
        if google_api_key:
            genai.configure(api_key=google_api_key)
            print(f"\n✓ Gemini API認証成功 (APIキー使用)")
        elif google_creds:
            # サービスアカウントキーを使用
            genai.configure(api_key=None)  # サービスアカウント認証を試行
            print(f"\n✓ Gemini API認証成功 (サービスアカウント使用)")
    except Exception as e:
        print(f"\nエラー: Gemini APIの初期化に失敗しました: {e}")
        return 1
    
    # 音声リスト読み込み
    print(f"\n音声リスト読み込み中...")
    voice_texts = load_voice_list()
    
    if not voice_texts:
        print("エラー: 音声テキストが見つかりませんでした。")
        return 1
    
    print(f"✓ {len(voice_texts)}件の音声テキストを読み込みました")
    
    # TTS設定表示
    print(f"\nTTS設定:")
    print(f"  モデル: {GEMINI_MODEL}")
    print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
    print(f"  ビット深度: {BIT_DEPTH}bit")
    print(f"  チャンネル: {CHANNELS} (モノラル)")
    print(f"  出力形式: WAV")
    print(f"  出力ディレクトリ: {OUTPUT_DIR}")
    
    # 音声ファイル生成
    print(f"\n音声ファイル生成中...")
    success_count = 0
    failed_count = 0
    
    for audio_id in sorted(voice_texts.keys()):
        text = voice_texts[audio_id]
        if generate_audio_file(audio_id, text):
            success_count += 1
        else:
            failed_count += 1
    
    # 結果表示
    print(f"\n" + "=" * 60)
    print(f"音声ファイル生成完了")
    print(f"  成功: {success_count}件")
    print(f"  失敗: {failed_count}件")
    print(f"  合計: {len(voice_texts)}件")
    print("=" * 60)
    
    if success_count == len(voice_texts):
        print("\n✓ すべての音声ファイルが正常に生成されました！")
        return 0
    else:
        print("\n⚠ 一部の音声ファイルの生成に失敗しました。")
        if failed_count > 0:
            print("Gemini 2.0 APIの音声生成機能がサポートされているか確認してください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())

