#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VOICEVOXを使用した日本語TTS（音声合成）スクリプト
クリアで綺麗なWAVファイルを一括生成
"""

import os
import sys
import requests
import json
from pathlib import Path
from typing import Optional

# VOICEVOX設定
VOICEVOX_URL = "http://localhost:50021"
SPEAKER_ID = 2  # 四国めたん・ノーマル

# 音声パラメータ
SPEED_SCALE = 1.15      # 話速
PITCH_SCALE = -0.05     # 音高
INTONATION_SCALE = 1.2  # 抑揚

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
CLIENT_DIR = PROJECT_ROOT / "clients" / "000"
JSON_FILE = CLIENT_DIR / "config" / "voice_lines_000.json"
OUTPUT_DIR = CLIENT_DIR / "audio"  # clients/000/audio/


def check_voicevox_connection() -> bool:
    """VOICEVOXエンジンが起動しているか確認"""
    try:
        response = requests.get(f"{VOICEVOX_URL}/speakers", timeout=5)
        if response.status_code == 200:
            print("✓ VOICEVOXエンジンに接続できました")
            return True
        else:
            print(f"✗ VOICEVOXエンジンへの接続に失敗しました (ステータス: {response.status_code})")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ VOICEVOXエンジンに接続できませんでした: {e}")
        print(f"  確認: {VOICEVOX_URL} が起動しているか確認してください")
        return False


def load_texts_from_json(json_file: Path) -> dict:
    """voice_lines_000.jsonからテキストを読み込む"""
    if not json_file.exists():
        print(f"✗ エラー: {json_file} が見つかりません")
        return {}
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 音声IDとテキストのペアを取得
        voice_texts = {}
        for audio_id, config in data.items():
            if isinstance(config, dict) and "text" in config:
                text = config["text"].strip()
                if text:  # 空のテキストをスキップ
                    voice_texts[audio_id] = text
        
        print(f"✓ {len(voice_texts)}件のテキストを読み込みました")
        return voice_texts
    except json.JSONDecodeError as e:
        print(f"✗ JSONの解析に失敗しました: {e}")
        return {}
    except Exception as e:
        print(f"✗ ファイル読み込みエラー: {e}")
        return {}


def get_audio_query(text: str) -> Optional[dict]:
    """音声クエリを取得"""
    try:
        response = requests.post(
            f"{VOICEVOX_URL}/audio_query",
            params={"text": text, "speaker": SPEAKER_ID},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  ✗ 音声クエリ取得失敗 (ステータス: {response.status_code})")
            return None
    except requests.exceptions.RequestException as e:
        print(f"  ✗ 音声クエリ取得エラー: {e}")
        return None


def synthesize_audio(audio_query: dict) -> Optional[bytes]:
    """音声を合成"""
    try:
        # パラメータを設定
        audio_query["speedScale"] = SPEED_SCALE
        audio_query["pitchScale"] = PITCH_SCALE
        audio_query["intonationScale"] = INTONATION_SCALE
        
        response = requests.post(
            f"{VOICEVOX_URL}/synthesis",
            params={"speaker": SPEAKER_ID},
            headers={"Content-Type": "application/json"},
            data=json.dumps(audio_query),
            timeout=30
        )
        
        if response.status_code == 200:
            return response.content
        else:
            print(f"  ✗ 音声合成失敗 (ステータス: {response.status_code})")
            return None
    except requests.exceptions.RequestException as e:
        print(f"  ✗ 音声合成エラー: {e}")
        return None


def ensure_output_directory():
    """出力ディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ 出力ディレクトリ: {OUTPUT_DIR}")


def generate_audio_file(audio_id: str, text: str) -> bool:
    """1件の音声ファイルを生成"""
    output_path = OUTPUT_DIR / f"{audio_id}.wav"
    
    # 既にファイルが存在する場合はスキップ
    if output_path.exists():
        print(f"\n[{audio_id}] スキップ: 既に存在します")
        return True
    
    print(f"\n[{audio_id}] 処理中: {text[:50]}...")
    
    # 音声クエリを取得
    audio_query = get_audio_query(text)
    if not audio_query:
        print(f"  ✗ 失敗: 音声クエリの取得に失敗しました")
        return False
    
    # 音声を合成
    audio_data = synthesize_audio(audio_query)
    if not audio_data:
        print(f"  ✗ 失敗: 音声合成に失敗しました")
        return False
    
    # VOICEVOXから取得したWAVデータをそのまま保存
    try:
        with open(output_path, 'wb') as f:
            f.write(audio_data)
        file_size = len(audio_data)
        print(f"  ✓ 保存成功: {output_path.name} ({file_size:,} bytes)")
        return True
    except Exception as e:
        print(f"  ✗ 保存失敗: {e}")
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("VOICEVOX 音声生成スクリプト")
    print("=" * 60)
    
    # VOICEVOX接続確認
    if not check_voicevox_connection():
        sys.exit(1)
    
    # 出力ディレクトリ作成
    ensure_output_directory()
    
    # JSONからテキスト読み込み
    voice_texts = load_texts_from_json(JSON_FILE)
    if not voice_texts:
        print("✗ 処理するテキストがありません")
        sys.exit(1)
    
    # 音声IDでソート（数値順）
    sorted_ids = sorted(voice_texts.keys(), key=lambda x: (len(x), x))
    total_count = len(sorted_ids)
    
    # 音声生成
    print(f"\n{total_count}件の音声を生成します...")
    print("-" * 60)
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    for idx, audio_id in enumerate(sorted_ids, 1):
        try:
            text = voice_texts[audio_id]
            result = generate_audio_file(audio_id, text)
            if result:
                # 既存ファイルの場合はスキップカウント
                output_path = OUTPUT_DIR / f"{audio_id}.wav"
                if output_path.exists() and idx > 1:  # 最初のチェックで既に存在していた場合
                    skip_count += 1
                else:
                    success_count += 1
            else:
                fail_count += 1
        except KeyboardInterrupt:
            print("\n\n⚠ ユーザーによって中断されました")
            break
        except Exception as e:
            print(f"  ✗ 予期しないエラー: {e}")
            fail_count += 1
    
    # 結果表示
    print("\n" + "=" * 60)
    print("生成完了")
    print("=" * 60)
    print(f"成功: {success_count}件")
    if skip_count > 0:
        print(f"スキップ: {skip_count}件（既存ファイル）")
    print(f"失敗: {fail_count}件")
    print(f"出力先: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()

