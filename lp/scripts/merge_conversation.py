#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LibertyCall デモ音声合成スクリプト
要件: pip install pydub
"""

from pydub import AudioSegment
import os
from pathlib import Path

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent.parent
AUDIO_DIR = PROJECT_ROOT / "lp" / "audio"
OUTPUT_DIR = AUDIO_DIR / "output"

# --- ファイル定義 ---
CUSTOMER_PATH = AUDIO_DIR / "12月13日（19-54）.m4a"
AI_VOICE_FILES = [
    "ai_voice_01.mp3", "ai_voice_02.mp3", "ai_voice_03.mp3",
    "ai_voice_04.mp3", "ai_voice_05.mp3", "ai_voice_06.mp3", "ai_voice_07.mp3"
]
OUTPUT_FILE = OUTPUT_DIR / "demo_reservation_final.mp3"

# --- 初期処理 ---
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not CUSTOMER_PATH.exists():
    print(f"エラー: お客様音声ファイルが見つかりません: {CUSTOMER_PATH}")
    exit(1)

print("▶ お客様音声を読み込み中...")
customer = AudioSegment.from_file(str(CUSTOMER_PATH))

# --- タイミング設定 ---
# あなたの音声に対して、AIのセリフを順に挿入
# 必要に応じて時間調整してください
insert_points = [0, 4.5, 8.5, 13.0, 18.0, 22.5, 27.0]  # 秒単位

print("▶ AI音声を読み込み中...")
ai_segments = []
for f in AI_VOICE_FILES:
    ai_path = AUDIO_DIR / f
    if not ai_path.exists():
        print(f"警告: AI音声ファイルが見つかりません: {ai_path}")
        continue
    ai_segments.append(AudioSegment.from_file(str(ai_path)))

if len(ai_segments) != len(AI_VOICE_FILES):
    print(f"エラー: AI音声ファイルが不足しています ({len(ai_segments)}/{len(AI_VOICE_FILES)})")
    exit(1)

# --- ミックス開始 ---
final_audio = AudioSegment.silent(duration=0)

cursor = 0
for i, ai_seg in enumerate(ai_segments):
    start_time = insert_points[i] * 1000
    end_time = (insert_points[i] + len(ai_seg) / 1000) * 1000
    
    # customerの該当区間までを追加
    if start_time > cursor:
        final_audio += customer[cursor:int(start_time)]
    
    # 少し無音を挿入してAI音声を追加
    final_audio += AudioSegment.silent(duration=400)
    final_audio += ai_seg
    cursor = int(end_time)

# 残りのcustomer音声を追加
if cursor < len(customer):
    final_audio += customer[cursor:]

# --- 音量正規化＆軽いEQ風処理 ---
final_audio = final_audio.apply_gain(-2.5)  # 全体音量調整
final_audio = final_audio.low_pass_filter(4000).high_pass_filter(250)  # 電話風EQ

# --- 書き出し ---
final_audio.export(str(OUTPUT_FILE), format="mp3", bitrate="192k")
print(f"✅ 完成: {OUTPUT_FILE}")

