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
DATA_FILE = Path(__file__).parent / "data.txt"  # scripts/data.txt
OUTPUT_DIR = Path(__file__).parent / "output"    # scripts/output


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


def load_texts_from_file(file_path: Path, max_lines: int = 100) -> list:
    """data.txtからテキストを読み込む"""
    if not file_path.exists():
        print(f"✗ エラー: {file_path} が見つかりません")
        return []
    
    texts = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f, 1):
            if idx > max_lines:
                break
            text = line.strip()
            if text:  # 空行をスキップ
                texts.append(text)
    
    print(f"✓ {len(texts)}件のテキストを読み込みました")
    return texts


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


def generate_audio_file(text: str, index: int) -> bool:
    """1件の音声ファイルを生成"""
    output_path = OUTPUT_DIR / f"call_{index:03d}.wav"
    
    print(f"\n[{index}] 処理中: {text[:30]}...")
    
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
    
    # テキスト読み込み
    texts = load_texts_from_file(DATA_FILE, max_lines=100)
    if not texts:
        print("✗ 処理するテキストがありません")
        sys.exit(1)
    
    # 音声生成
    print(f"\n{len(texts)}件の音声を生成します...")
    print("-" * 60)
    
    success_count = 0
    fail_count = 0
    
    for idx, text in enumerate(texts, 1):
        try:
            if generate_audio_file(text, idx):
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
    print(f"失敗: {fail_count}件")
    print(f"出力先: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()

