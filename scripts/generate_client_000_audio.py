#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クライアント000用の音声ファイル一括生成スクリプト

使い方:
    python scripts/generate_client_000_audio.py

生成されるファイル:
    - clients/000/audio/{template_id}.wav (voice_lines_000.json に定義された全ID)
    - clients/000/voice_list_000.tsv

設定ファイル:
    - clients/000/config/voice_lines_000.json
      - 各テンプレートIDごとに {"text", "voice", "rate"} を定義
      - voice: Google Cloud TTS の音声名（例: "ja-JP-Neural2-B"）
      - rate: 話す速度（例: 1.1）

依存パッケージ:
    - google-cloud-texttospeech: pip install google-cloud-texttospeech

設定:
    - TTSエンジン: Google Cloud TTS (Neural2)
    - デフォルト音声: ja-JP-Neural2-B
    - デフォルト速度: 1.1
    - 出力形式: WAV (LINEAR16, 16bit, モノラル, 44100Hz)
    - 各テンプレートIDの voice/rate は voice_lines_000.json から読み込む
"""

import os
import sys
import json
import wave
from pathlib import Path
from google.cloud import texttospeech

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
AUDIO_DIR = CLIENT_DIR / "audio"
TSV_FILE = CLIENT_DIR / "voice_list_000.tsv"
VOICE_LINES_JSON = CLIENT_DIR / "config" / "voice_lines_000.json"

# TTS設定（デフォルト値、voice_lines_000.json で個別に上書き可能）
DEFAULT_SPEAKING_RATE = 1.1
DEFAULT_VOICE_NAME = "ja-JP-Neural2-B"  # デフォルト音声
DEFAULT_LANGUAGE_CODE = "ja-JP"
SAMPLE_RATE = 44100  # サンプリングレート（Hz）

# voice_lines_000.json から音声リストを読み込む
def load_voice_lines():
    """voice_lines_000.json から音声リストを読み込む"""
    if not VOICE_LINES_JSON.exists():
        print(f"ERROR: {VOICE_LINES_JSON} が見つかりません。")
        sys.exit(1)
    
    with open(VOICE_LINES_JSON, 'r', encoding='utf-8') as f:
        voice_lines = json.load(f)
    
    return voice_lines

VOICE_LINES = load_voice_lines()


def check_credentials():
    """Google Cloud認証情報の確認"""
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("エラー: GOOGLE_APPLICATION_CREDENTIALS 環境変数が設定されていません。")
        print("GCPの認証JSONファイルのパスを設定してください。")
        print("例: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json")
        return False
    return True


def ensure_directories():
    """必要なディレクトリを作成"""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ ディレクトリ確認: {AUDIO_DIR}")


def extract_language_code(voice_name: str) -> str:
    """
    voice_name から language_code を抽出
    
    例: "ja-JP-Neural2-B" -> "ja-JP"
    """
    if "-Neural" in voice_name:
        return voice_name.split("-Neural")[0]
    elif "-WaveNet" in voice_name:
        return voice_name.split("-WaveNet")[0]
    elif "-Standard" in voice_name:
        return voice_name.split("-Standard")[0]
    else:
        # フォールバック: 最初の2つの部分を結合
        parts = voice_name.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
    return DEFAULT_LANGUAGE_CODE


def generate_audio(voice_id: str, voice_config: dict, client: texttospeech.TextToSpeechClient) -> bool:
    """
    音声ファイルを生成（Google Cloud TTS）
    
    Args:
        voice_id: 音声ID（例: "003"）
        voice_config: voice_lines_000.json のエントリ（{"text": "...", "voice": "...", "rate": ...}）
        client: TextToSpeechClientインスタンス
    
    Returns:
        成功した場合True
    """
    try:
        output_wav = AUDIO_DIR / f"{voice_id}.wav"
        
        text = voice_config.get("text", "")
        voice_name = voice_config.get("voice", DEFAULT_VOICE_NAME)
        speaking_rate = voice_config.get("rate", DEFAULT_SPEAKING_RATE)
        
        if not text:
            print(f"  ⚠ {voice_id}: テキストが空のためスキップ")
            return False
        
        # language_code を抽出
        language_code = extract_language_code(voice_name)
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        
        # 音声設定（クライアント000の現在の設定: pitch=0.0, speed=1.2）
        # voice_lines_000.jsonのrateを1.2に調整（現在のTTS設定に合わせる）
        adjusted_rate = 1.2  # クライアント000の現在の設定
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=adjusted_rate,
            pitch=0.0,  # クライアント000の現在の設定
        )
        
        # 音声合成実行
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(output_wav), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        print(f"  ✓ {voice_id}.wav 生成完了 (voice={voice_name}, rate=1.2, pitch=0.0)")
        return True
        
    except Exception as e:
        print(f"  ✗ {voice_id}.wav 生成失敗: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_tsv_file():
    """voice_list_000.tsv ファイルを生成"""
    try:
        with open(TSV_FILE, 'w', encoding='utf-8') as f:
            # ID順にソートして書き出し（数値としてソート、文字列としてソートの両方に対応）
            def sort_key(x):
                try:
                    return (0, int(x))
                except ValueError:
                    return (1, x)
            
            for voice_id in sorted(VOICE_LINES.keys(), key=sort_key):
                voice_config = VOICE_LINES[voice_id]
                text = voice_config.get("text", "")
                f.write(f"{voice_id}\t{text}\n")
        
        print(f"✓ TSVファイル生成完了: {TSV_FILE}")
        return True
        
    except Exception as e:
        print(f"✗ TSVファイル生成失敗: {e}")
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("クライアント000用音声ファイル一括生成")
    print("=" * 60)
    
    # 認証情報確認
    if not check_credentials():
        return 1
    
    # ディレクトリ確認
    ensure_directories()
    
    # Google Cloud TTSクライアント初期化
    print(f"\nTTS設定:")
    print(f"  デフォルト音声: {DEFAULT_VOICE_NAME}")
    print(f"  デフォルト速度: {DEFAULT_SPEAKING_RATE}x")
    print(f"  サンプリングレート: {SAMPLE_RATE}Hz")
    print(f"  出力形式: WAV (LINEAR16, 16bit, モノラル)")
    print(f"  設定ファイル: {VOICE_LINES_JSON}")
    
    try:
        client = texttospeech.TextToSpeechClient()
    except Exception as e:
        print(f"\nエラー: Google Cloud TTSクライアントの初期化に失敗しました: {e}")
        return 1
    
    # 音声ファイル生成
    print(f"\n音声ファイル生成中... ({len(VOICE_LINES)}件)")
    success_count = 0
    skipped_count = 0
    
    # ID順にソート（数値としてソート、文字列としてソートの両方に対応）
    def sort_key(x):
        try:
            return (0, int(x[0]))
        except ValueError:
            return (1, x[0])
    
    for voice_id, voice_config in sorted(VOICE_LINES.items(), key=sort_key):
        # 000.wavは触らない（スキップ）
        if voice_id == "000":
            print(f"  ⏭ {voice_id}.wav: スキップ（保持）")
            skipped_count += 1
            continue
        if generate_audio(voice_id, voice_config, client):
            success_count += 1
        else:
            skipped_count += 1
    
    print(f"\n音声ファイル生成完了: 成功 {success_count}件 / スキップ {skipped_count}件 / 合計 {len(VOICE_LINES)}件")
    
    # TSVファイル生成
    print(f"\nTSVファイル生成中...")
    if generate_tsv_file():
        print("\n" + "=" * 60)
        print("✔ 全音声を再生成しました")
        print("=" * 60)
        print(f"\n出力先: {AUDIO_DIR}")
        print(f"  - 音声ファイル: {success_count}件")
        print(f"  - TSVファイル: {TSV_FILE}")
        print(f"  - 設定ファイル: {VOICE_LINES_JSON}")
        
        # 生成されたファイルの一覧を表示（最初の10件と最後の10件）
        generated_files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda x: (len(x.stem), x.stem))
        if generated_files:
            print(f"\n生成されたファイル例:")
            for f in generated_files[:5]:
                print(f"  - {f.name}")
            if len(generated_files) > 10:
                print(f"  ... (他 {len(generated_files) - 10} 件) ...")
            for f in generated_files[-5:]:
                print(f"  - {f.name}")
        
        return 0
    else:
        print("\nエラー: TSVファイルの生成に失敗しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
