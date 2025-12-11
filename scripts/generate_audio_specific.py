#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
特定のテンプレートIDの音声ファイルを再生成するスクリプト

使い方:
    python3 scripts/generate_audio_specific.py 005 006 085 086 087
"""

import json
import sys
import wave
from pathlib import Path
from google.cloud import texttospeech

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
AUDIO_DIR = CLIENT_DIR / "audio"
VOICE_LINES_JSON = CLIENT_DIR / "config" / "voice_lines_000.json"

# TTS設定
DEFAULT_VOICE_NAME = "ja-JP-Neural2-B"
DEFAULT_LANGUAGE_CODE = "ja-JP"
SAMPLE_RATE = 44100  # サンプリングレート（Hz）

def load_voice_lines():
    """voice_lines_000.json から音声リストを読み込む"""
    if not VOICE_LINES_JSON.exists():
        print(f"ERROR: {VOICE_LINES_JSON} が見つかりません。")
        sys.exit(1)
    
    with open(VOICE_LINES_JSON, 'r', encoding='utf-8') as f:
        voice_lines = json.load(f)
    
    return voice_lines

def extract_language_code(voice_name: str) -> str:
    """音声名から言語コードを抽出"""
    # "ja-JP-Neural2-B" -> "ja-JP"
    parts = voice_name.split('-')
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return DEFAULT_LANGUAGE_CODE

def generate_audio(voice_id: str, voice_config: dict, client: texttospeech.TextToSpeechClient) -> bool:
    """音声ファイルを生成（Google Cloud TTS）"""
    try:
        output_wav = AUDIO_DIR / f"{voice_id}.wav"
        
        text = voice_config.get("text", "")
        voice_name = voice_config.get("voice", DEFAULT_VOICE_NAME)
        speaking_rate = voice_config.get("rate", 1.1)
        
        if not text:
            print(f"  ⚠ {voice_id}: テキストが空のためスキップ")
            return False
        
        print(f"  📝 {voice_id}: {text[:50]}...")
        
        # language_code を抽出
        language_code = extract_language_code(voice_name)
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        
        # 音声設定
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV PCM16
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=speaking_rate,
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
        
        print(f"  ✓ {voice_id}.wav 生成完了 (voice={voice_name}, rate={speaking_rate})")
        return True
        
    except Exception as e:
        print(f"  ✗ {voice_id}.wav 生成失敗: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """メイン処理"""
    if len(sys.argv) < 2:
        print("使い方: python3 scripts/generate_audio_specific.py <template_id1> [template_id2] ...")
        print("例: python3 scripts/generate_audio_specific.py 005 006 085 086 087")
        sys.exit(1)
    
    template_ids = sys.argv[1:]
    
    print("=" * 60)
    print(f"音声ファイル再生成: {', '.join(template_ids)}")
    print("=" * 60)
    
    # 認証情報確認
    if not Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).exists():
        print("⚠ 警告: GOOGLE_APPLICATION_CREDENTIALS が設定されていないか、ファイルが見つかりません。")
        print("   続行しますが、認証エラーが発生する可能性があります。")
    
    # ディレクトリ確認
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    
    # 音声リストを読み込む
    voice_lines = load_voice_lines()
    
    # TTSクライアントを作成
    try:
        client = texttospeech.TextToSpeechClient()
    except Exception as e:
        print(f"✗ TTSクライアントの作成に失敗しました: {e}")
        sys.exit(1)
    
    # 指定されたテンプレートIDの音声を生成
    success_count = 0
    fail_count = 0
    
    for template_id in template_ids:
        if template_id not in voice_lines:
            print(f"  ⚠ {template_id}: voice_lines_000.json に存在しません")
            fail_count += 1
            continue
        
        voice_config = voice_lines[template_id]
        if generate_audio(template_id, voice_config, client):
            success_count += 1
        else:
            fail_count += 1
    
    print("=" * 60)
    print(f"完了: 成功 {success_count}件, 失敗 {fail_count}件")
    print("=" * 60)
    
    if fail_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    import os
    main()

