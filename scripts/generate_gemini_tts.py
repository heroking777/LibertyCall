#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 2.0 APIを使用した日本語TTS（音声合成）スクリプト

Vertex AI SDKまたはMultimodal Live APIを使用して音声を生成します。

voice_list_000.tsvから000-003の音声ファイルを生成します。

使い方:
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
    export GOOGLE_CLOUD_PROJECT="your-project-id"
    export GOOGLE_CLOUD_LOCATION="us-central1"
    
    python scripts/generate_gemini_tts.py

生成されるファイル:
    - clients/000/audio/000.wav
    - clients/000/audio/001.wav
    - clients/000/audio/002.wav
    - clients/000/audio/003.wav

依存パッケージ:
    - google-cloud-aiplatform: pip install google-cloud-aiplatform
"""

import os
import sys
import wave
import io
import json
import base64
from pathlib import Path
from typing import Optional

try:
    from google.cloud import aiplatform
    from vertexai.generative_models import GenerativeModel
    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False
    print("警告: google-cloud-aiplatform がインストールされていません。")
    print("インストール: pip install google-cloud-aiplatform")

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
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    
    if not google_creds:
        print("エラー: GOOGLE_APPLICATION_CREDENTIALS 環境変数が設定されていません。")
        print("設定例: export GOOGLE_APPLICATION_CREDENTIALS=\"/path/to/credentials.json\"")
        return False
    
    if not os.path.exists(google_creds):
        print(f"エラー: 認証ファイルが見つかりません: {google_creds}")
        return False
    
    if not project_id:
        print("警告: GOOGLE_CLOUD_PROJECT 環境変数が設定されていません。")
        print("認証ファイルからプロジェクトIDを読み取ります。")
    
    return True


def get_project_id_from_credentials() -> Optional[str]:
    """認証ファイルからプロジェクトIDを取得"""
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        return None
    
    try:
        with open(creds_path, 'r') as f:
            creds = json.load(f)
            return creds.get('project_id')
    except Exception as e:
        print(f"警告: 認証ファイルからプロジェクトIDを読み取れませんでした: {e}")
        return None


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


def synthesize_with_vertex_ai(text: str, project_id: str, location: str = "us-central1") -> Optional[bytes]:
    """
    Vertex AI SDKを使用してテキストから音声を合成する
    
    Args:
        text: 音声化するテキスト
        project_id: Google Cloud プロジェクトID
        location: リージョン（デフォルト: us-central1）
    
    Returns:
        音声データ（bytes）または None
    """
    try:
        # Vertex AIを初期化
        aiplatform.init(project=project_id, location=location)
        
        # Gemini 2.0 Flash モデルを取得
        model = GenerativeModel(GEMINI_MODEL)
        
        # 音声生成のリクエスト
        # 注: Vertex AIのGenerativeModelは主にテキスト生成用ですが、
        # 音声生成機能がある場合は、適切なメソッドを使用します
        
        # プロンプトを作成
        prompt = f"以下の日本語テキストを自然な音声で読み上げてください: {text}"
        
        # 音声生成を試行
        # 注: 実際のAPIでは、音声生成専用のメソッドやパラメータがある可能性があります
        try:
            # generate_contentを使用（音声生成がサポートされている場合）
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.7,
                    "max_output_tokens": 8192,
                }
            )
            
            # レスポンスから音声データを取得
            # 注: 実際のAPIレスポンス形式に合わせて調整が必要です
            if hasattr(response, 'audio_content'):
                return response.audio_content
            elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'audio_data'):
                            # Base64エンコードされた音声データの場合
                            if isinstance(part.audio_data, str):
                                return base64.b64decode(part.audio_data)
                            return part.audio_data
                        elif hasattr(part, 'inline_data') and hasattr(part.inline_data, 'data'):
                            # inline_dataに音声データがある場合
                            return base64.b64decode(part.inline_data.data)
            
            # テキストが返された場合（音声生成がサポートされていない場合）
            print(f"警告: Vertex AIは音声データではなくテキストを返しました。")
            print(f"レスポンス: {response.text if hasattr(response, 'text') else 'N/A'}")
            return None
            
        except Exception as api_error:
            print(f"API呼び出しエラー: {api_error}")
            import traceback
            traceback.print_exc()
            return None
        
    except Exception as e:
        print(f"エラー: Vertex AI音声合成に失敗しました: {e}")
        import traceback
        traceback.print_exc()
        return None


def synthesize_with_multimodal_live_api(text: str, project_id: str, location: str = "us-central1") -> Optional[bytes]:
    """
    Multimodal Live APIを使用してテキストから音声を合成する（REST API版）
    
    Args:
        text: 音声化するテキスト
        project_id: Google Cloud プロジェクトID
        location: リージョン（デフォルト: us-central1）
    
    Returns:
        音声データ（bytes）または None
    """
    try:
        import requests
        from google.auth import default
        from google.auth.transport.requests import Request
        
        # 認証情報を取得（適切なスコープを指定）
        credentials, _ = default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        credentials.refresh(Request())
        
        # Vertex AI API のエンドポイント
        endpoint = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{GEMINI_MODEL}:generateContent"
        
        # リクエストボディ
        # 注: 実際のGemini 2.0 APIの音声生成機能のパラメータは、最新のAPIドキュメントを確認してください
        payload = {
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": text
                }]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 8192,
            }
        }
        
        # リクエストヘッダー
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        
        # API呼び出し
        response = requests.post(endpoint, json=payload, headers=headers)
        
        # エラーレスポンスの詳細を確認
        if response.status_code != 200:
            print(f"APIエラー: {response.status_code}")
            try:
                error_detail = response.json()
                print(f"エラー詳細: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
            except:
                print(f"エラーレスポンス: {response.text[:500]}")
            response.raise_for_status()
        
        # レスポンスから音声データを取得
        result = response.json()
        
        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    if "inlineData" in part:
                        # Base64エンコードされた音声データ
                        audio_data = part["inlineData"]["data"]
                        return base64.b64decode(audio_data)
                    elif "text" in part:
                        # テキストが返された場合
                        print(f"レスポンス: テキストが返されました - {part['text'][:100]}")
        
        # デバッグ: レスポンスの詳細を表示
        print(f"警告: 音声データが見つかりませんでした。")
        print(f"レスポンス形式: {list(result.keys())}")
        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            print(f"候補のキー: {list(candidate.keys())}")
            if "content" in candidate:
                print(f"コンテンツのキー: {list(candidate['content'].keys())}")
                if "parts" in candidate["content"]:
                    for i, part in enumerate(candidate["content"]["parts"]):
                        print(f"パート {i} のキー: {list(part.keys())}")
        
        # 注: Gemini 2.0 APIは音声生成機能を直接サポートしていない可能性があります
        # 実際の音声生成には、Google Cloud Text-to-Speech APIを使用する必要があるかもしれません
        return None
        
    except ImportError:
        print("エラー: requests がインストールされていません。")
        print("インストール: pip install requests")
        return None
    except Exception as e:
        print(f"エラー: Multimodal Live API音声合成に失敗しました: {e}")
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


def generate_audio_file(audio_id: str, text: str, project_id: str, location: str) -> bool:
    """
    Vertex AIまたはMultimodal Live APIを使用して音声ファイルを生成
    
    Args:
        audio_id: 音声ID（例: "000"）
        text: 音声化するテキスト
        project_id: Google Cloud プロジェクトID
        location: リージョン
    
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
        
        # まずVertex AI SDKを試行
        audio_data = None
        if VERTEX_AI_AVAILABLE:
            print(f"  Vertex AI SDKを使用して音声生成を試行...")
            audio_data = synthesize_with_vertex_ai(text, project_id, location)
        
        # Vertex AIが失敗した場合はMultimodal Live APIを試行
        if not audio_data:
            print(f"  Multimodal Live APIを使用して音声生成を試行...")
            audio_data = synthesize_with_multimodal_live_api(text, project_id, location)
        
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
    print("Gemini 2.0 API 日本語TTS音声生成 (Vertex AI / Multimodal Live API)")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # ディレクトリ確認
    ensure_directories()
    
    # プロジェクトIDとリージョンを取得
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project_id:
        project_id = get_project_id_from_credentials()
    
    if not project_id:
        print("エラー: プロジェクトIDが取得できませんでした。")
        print("GOOGLE_CLOUD_PROJECT 環境変数を設定するか、認証ファイルにproject_idが含まれていることを確認してください。")
        return 1
    
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    print(f"\n✓ 認証情報確認完了")
    print(f"  プロジェクトID: {project_id}")
    print(f"  リージョン: {location}")
    
    if VERTEX_AI_AVAILABLE:
        print(f"✓ Vertex AI SDK 利用可能")
    else:
        print(f"⚠ Vertex AI SDK 未インストール (Multimodal Live APIのみ使用)")
    
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
        if generate_audio_file(audio_id, text, project_id, location):
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
