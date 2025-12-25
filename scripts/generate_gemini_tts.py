#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 2.5 APIを使用した日本語TTS（音声合成）スクリプト

google.genaiパッケージとspeech_configを使用して音声を生成します。

voice_list_000.tsvから000-003の音声ファイルを生成します。

使い方:
    export GOOGLE_API_KEY="your-api-key"
    # または
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
    
    python scripts/generate_gemini_tts.py

生成されるファイル:
    - clients/000/audio/000.wav
    - clients/000/audio/001.wav
    - clients/000/audio/002.wav
    - clients/000/audio/003.wav

依存パッケージ:
    - google-genai: pip install google-genai
"""

import os
import sys
import wave
import io
import base64
from pathlib import Path
from typing import Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("エラー: google-genai がインストールされていません。")
    print("インストール: pip install google-genai")

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
TSV_FILE = CLIENT_DIR / "voice_list_000.tsv"
OUTPUT_DIR = CLIENT_DIR / "audio"

# TTS設定
SAMPLE_RATE = 24000  # 24kHz
BIT_DEPTH = 16  # 16bit
CHANNELS = 1  # モノラル

# Gemini 2.5 モデル名
GEMINI_MODEL = "gemini-2.5-flash"


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


def synthesize_with_gemini_2_5(text: str, api_key: Optional[str] = None) -> Optional[bytes]:
    """
    Gemini 2.5 APIを使用してテキストから音声を合成する
    
    Args:
        text: 音声化するテキスト
        api_key: APIキー（Noneの場合は環境変数から取得）
    
    Returns:
        音声データ（bytes）または None
    """
    try:
        if not GENAI_AVAILABLE:
            print("エラー: google-genai がインストールされていません。")
            return None
        
        # クライアントを初期化
        if api_key:
            client = genai.Client(api_key=api_key)
        else:
            # 環境変数からAPIキーを取得
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                # サービスアカウントキーを使用する場合（Vertex AI）
                creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
                
                if creds_path and project_id:
                    import vertexai
                    vertexai.init(project=project_id, location=location)
                    client = genai.Client(vertexai=True)
                else:
                    print("エラー: APIキーまたは認証情報（プロジェクトID含む）が見つかりません。")
                    return None
            else:
                client = genai.Client(api_key=api_key)
        
        # 音声生成リクエスト
        # speech_configを使用して音声を生成
        # ユーザー提供のコード例に基づく実装
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name='Charon'  # 日本語対応ボイス
                            )
                        )
                    )
                )
            )
        except Exception as config_error:
            print(f"警告: speech_configの設定でエラーが発生しました: {config_error}")
            print(f"代替方法を試します...")
            # シンプルな方法を試す
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=text
            )
        
        # 音声データを取得（ユーザー提供のコード例に基づく）
        # response.candidates[0].content.parts[0].inline_data.data
        try:
            if hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    if len(candidate.content.parts) > 0:
                        part = candidate.content.parts[0]
                        
                        # inline_dataから音声データを取得
                        if hasattr(part, 'inline_data') and part.inline_data is not None:
                            inline_data = part.inline_data
                            if hasattr(inline_data, 'data') and inline_data.data:
                                # Base64エンコードされた音声データ
                                audio_data = inline_data.data
                                print(f"✓ 音声データを取得しました (Base64サイズ: {len(audio_data)} bytes)")
                                decoded_data = base64.b64decode(audio_data)
                                print(f"✓ デコード後のサイズ: {len(decoded_data)} bytes")
                                return decoded_data
                        
                        # テキストが返された場合は警告
                        if hasattr(part, 'text') and part.text:
                            print(f"警告: テキストが返されました（音声データではありません）: {part.text[:100]}")
                            print(f"speech_configが正しく適用されていない可能性があります。")
        except Exception as e:
            print(f"エラー: 音声データの取得中にエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"警告: 音声データが見つかりませんでした。")
        return None
        
    except Exception as e:
        print(f"エラー: Gemini 2.5 API音声合成に失敗しました: {e}")
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


def generate_audio_file(audio_id: str, text: str, api_key: Optional[str] = None) -> bool:
    """
    Gemini 2.5 APIを使用して音声ファイルを生成
    
    Args:
        audio_id: 音声ID（例: "000"）
        text: 音声化するテキスト
        api_key: APIキー（Noneの場合は環境変数から取得）
    
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
        
        # Gemini 2.5 APIで音声合成
        audio_data = synthesize_with_gemini_2_5(text, api_key)
        
        if not audio_data:
            print(f"  ✗ {audio_id}: 音声合成に失敗しました")
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
    print("Gemini 2.5 API 日本語TTS音声生成")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # ディレクトリ確認
    ensure_directories()
    
    # APIキーを取得
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if api_key:
        print(f"\n✓ APIキー認証を使用")
    elif google_creds:
        print(f"\n✓ サービスアカウント認証を使用")
    else:
        print(f"\n✗ 認証情報が見つかりません")
        return 1
    
    if not GENAI_AVAILABLE:
        print("エラー: google-genai がインストールされていません。")
        print("インストール: pip install google-genai")
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
    print(f"  ボイス: Charon (日本語対応)")
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
        if generate_audio_file(audio_id, text, api_key):
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
        return 1


if __name__ == "__main__":
    sys.exit(main())
