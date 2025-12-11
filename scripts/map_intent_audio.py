#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
intent と wav ファイル名を対応付けるスクリプト

使い方:
    python3 scripts/map_intent_audio.py '["INQUIRY", "GREETING"]'
"""

import sys
import json
import os
from pathlib import Path

# プロジェクトルートを取得
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TTS_TEST_DIR = PROJECT_ROOT / "tts_test"

# intent と音声ファイルのマッピング
INTENT_TO_AUDIO = {
    "GREETING": ["004_moshimoshi.wav", "moshimoshi.wav", "greeting.wav"],
    "INQUIRY": ["005_inquiry.wav", "inquiry.wav", "question.wav"],
    "SALES_CALL": ["006_sales.wav", "sales.wav", "introduction.wav"],
    "HANDOFF_REQUEST": ["015_handoff.wav", "handoff.wav", "transfer.wav", "担当者.wav"],
    "HANDOFF_YES": ["yes.wav", "ok.wav", "承知.wav"],
    "HANDOFF_NO": ["no.wav", "いいえ.wav", "不要.wav"],
    "END_CALL": ["018_end.wav", "end.wav", "goodbye.wav", "086.wav", "087.wav"],
    "NOT_HEARD": ["110.wav", "not_heard.wav", "noise.wav"],
    "UNKNOWN": ["unknown.wav"],
}

def find_audio_files(intents: list[str]) -> list[str]:
    """
    intentリストから対応する音声ファイルを検索
    
    :param intents: intent名のリスト
    :return: 見つかった音声ファイルのパスリスト
    """
    found_files = []
    
    if not TTS_TEST_DIR.exists():
        return found_files
    
    # すべてのWAVファイルを取得
    all_wav_files = list(TTS_TEST_DIR.glob("*.wav"))
    
    for intent in intents:
        # マッピングから候補ファイル名を取得
        candidates = INTENT_TO_AUDIO.get(intent, [])
        
        # 候補ファイル名を含むファイルを検索
        for candidate in candidates:
            # 完全一致
            for wav_file in all_wav_files:
                if wav_file.name == candidate:
                    found_files.append(str(wav_file))
                    break
            
            # 部分一致（ファイル名に候補が含まれる）
            for wav_file in all_wav_files:
                if candidate.replace(".wav", "").lower() in wav_file.name.lower():
                    if str(wav_file) not in found_files:
                        found_files.append(str(wav_file))
        
        # intent名自体をファイル名に含むファイルも検索
        intent_lower = intent.lower()
        for wav_file in all_wav_files:
            if intent_lower in wav_file.name.lower():
                if str(wav_file) not in found_files:
                    found_files.append(str(wav_file))
    
    return found_files

def main():
    if len(sys.argv) < 2:
        print("使い方: python3 scripts/map_intent_audio.py '<json_array>'")
        print("例: python3 scripts/map_intent_audio.py '[\"INQUIRY\", \"GREETING\"]'")
        sys.exit(1)
    
    # JSON配列をパース
    try:
        intents = json.loads(sys.argv[1])
        if not isinstance(intents, list):
            print("❌ エラー: JSON配列を指定してください。", file=sys.stderr)
            sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ エラー: JSONのパースに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 音声ファイルを検索
    audio_files = find_audio_files(intents)
    
    # スペース区切りで出力（シェルスクリプトで使いやすい形式）
    if audio_files:
        print(" ".join(audio_files))
    else:
        # ファイルが見つからない場合は空文字を出力
        print("", end="")

if __name__ == "__main__":
    main()

