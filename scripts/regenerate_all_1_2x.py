#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
000以外のすべての音声ファイルを1.2xで再生成するスクリプト
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
VOICE_LINES_JSON = CLIENT_DIR / "config" / "voice_lines_000.json"

# 001と002の設定（generate_initial_greeting.pyから）
INITIAL_LINES = {
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

def load_voice_lines():
    """voice_lines_000.jsonから音声リストを読み込む"""
    if not VOICE_LINES_JSON.exists():
        print(f"ERROR: {VOICE_LINES_JSON} が見つかりません。")
        return {}
    
    with open(VOICE_LINES_JSON, 'r', encoding='utf-8') as f:
        voice_lines = json.load(f)
    
    return voice_lines

def extract_language_code(voice_name: str) -> str:
    """voice_nameからlanguage_codeを抽出"""
    if "-Neural" in voice_name:
        return voice_name.split("-Neural")[0]
    elif "-WaveNet" in voice_name:
        return voice_name.split("-WaveNet")[0]
    elif "-Standard" in voice_name:
        return voice_name.split("-Standard")[0]
    else:
        parts = voice_name.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
    return LANGUAGE_CODE

def generate_audio(audio_id: str, config: dict, client: texttospeech.TextToSpeechClient) -> bool:
    """音声ファイルを生成"""
    try:
        output_file = AUDIO_DIR / f"{audio_id}.wav"
        
        text = config.get("text", "")
        voice_name = config.get("voice", "ja-JP-Neural2-B")
        speaking_rate = config.get("rate", 1.2)  # 1.2xに統一
        
        if not text:
            print(f"  ⚠ {audio_id}: テキストが空のためスキップ")
            return False
        
        # language_codeを抽出
        language_code = extract_language_code(voice_name)
        
        # 音声合成入力
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        # 音声選択パラメータ
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        
        # 音声設定（1.2xに統一）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            speaking_rate=1.2,  # 強制的に1.2x
        )
        
        # 音声合成実行
        print(f"  📝 {audio_id}: {text[:50]}... (rate=1.2x)")
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 出力ディレクトリを作成
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        
        # LINEAR16はraw PCMなので、WAVヘッダーを付けて保存
        with wave.open(str(output_file), "wb") as wf:
            wf.setnchannels(1)  # モノラル
            wf.setsampwidth(2)  # 16bit (2 bytes)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(response.audio_content)
        
        print(f"  ✓ {audio_id}.wav 生成完了")
        return True
        
    except Exception as e:
        print(f"  ✗ {audio_id}.wav 生成失敗: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """メイン処理"""
    print("=" * 60)
    print("000以外のすべての音声ファイルを1.2xで再生成")
    print("=" * 60)
    
    # voice_lines_000.jsonから読み込み
    voice_lines = load_voice_lines()
    
    # 000以外のIDを抽出
    audio_ids = []
    
    # 001と002を追加
    for audio_id in ["001", "002"]:
        if audio_id in INITIAL_LINES:
            audio_ids.append((audio_id, INITIAL_LINES[audio_id]))
    
    # voice_lines_000.jsonから000以外を追加
    for audio_id, config in voice_lines.items():
        if audio_id != "000":  # 000は除外
            # rateを1.2に変更
            config_copy = config.copy()
            config_copy["rate"] = 1.2
            audio_ids.append((audio_id, config_copy))
    
    print(f"\n生成対象: {len(audio_ids)}件（000を除く）")
    
    # Google Cloud TTSクライアント初期化
    try:
        client = texttospeech.TextToSpeechClient()
    except Exception as e:
        print(f"\nエラー: Google Cloud TTSクライアントの初期化に失敗しました: {e}")
        return 1
    
    # 音声ファイル生成
    print(f"\n音声ファイル生成中...")
    success_count = 0
    failed_count = 0
    
    # ID順にソート
    def sort_key(x):
        try:
            return (0, int(x[0]))
        except ValueError:
            return (1, x[0])
    
    for audio_id, config in sorted(audio_ids, key=sort_key):
        if generate_audio(audio_id, config, client):
            success_count += 1
        else:
            failed_count += 1
    
    print(f"\n" + "=" * 60)
    print(f"生成完了: 成功 {success_count}件 / 失敗 {failed_count}件 / 合計 {len(audio_ids)}件")
    print("=" * 60)
    
    if failed_count == 0:
        print(f"\n✔ すべての音声ファイルを1.2xで再生成しました")
        print(f"出力先: {AUDIO_DIR}")
        return 0
    else:
        print(f"\n✗ 一部の音声ファイルの生成に失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())

