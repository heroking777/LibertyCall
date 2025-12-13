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
customer_duration = len(customer) / 1000.0
print(f"  お客様音声の長さ: {customer_duration:.2f}秒")

print("▶ AI音声を読み込み中...")
ai_segments = []
for f in AI_VOICE_FILES:
    ai_path = AUDIO_DIR / f
    if not ai_path.exists():
        print(f"警告: AI音声ファイルが見つかりません: {ai_path}")
        continue
    seg = AudioSegment.from_file(str(ai_path))
    ai_segments.append(seg)
    print(f"  {f}: {len(seg)/1000:.2f}秒")

if len(ai_segments) != len(AI_VOICE_FILES):
    print(f"エラー: AI音声ファイルが不足しています ({len(ai_segments)}/{len(AI_VOICE_FILES)})")
    exit(1)

# --- 会話形式で合成 ---
# AIと人間が交互に会話する形式
# パターン: AI → 人間 → AI → 人間 → ...
# 人間の音声を適切な長さに分割して配置

print("\n▶ 会話形式で合成中...")

# 人間の音声を7つのセクションに分割（AI音声の数に合わせる）
# 各セクションの長さを計算（均等分割ではなく、AI音声の長さに合わせて調整）
customer_sections = []
total_ai_duration = sum(len(seg) for seg in ai_segments) / 1000.0
remaining_customer = customer

# 人間の音声をAI音声の間に入れるように分割
# 各AI音声の後に人間の応答が来る想定
section_durations = [
    customer_duration * 0.15,  # 最初の応答（短め）
    customer_duration * 0.12,  # 2番目
    customer_duration * 0.13,  # 3番目
    customer_duration * 0.12,  # 4番目
    customer_duration * 0.15,  # 5番目
    customer_duration * 0.10,  # 6番目
    customer_duration * 0.23,  # 最後（長め）
]

cursor = 0
for i, duration in enumerate(section_durations):
    end_pos = min(cursor + int(duration * 1000), len(customer))
    section = customer[cursor:end_pos]
    customer_sections.append(section)
    cursor = end_pos
    print(f"  人間セクション{i+1}: {len(section)/1000:.2f}秒")

# 会話形式で合成: AI → 人間 → AI → 人間 → ...
final_audio = AudioSegment.silent(duration=0)

for i in range(len(ai_segments)):
    # AI音声を追加
    print(f"  AI音声{i+1}を追加...")
    final_audio += ai_segments[i]
    final_audio += AudioSegment.silent(duration=300)  # 少し間を空ける
    
    # 人間の応答を追加
    if i < len(customer_sections):
        print(f"  人間応答{i+1}を追加...")
        final_audio += customer_sections[i]
        final_audio += AudioSegment.silent(duration=300)  # 少し間を空ける

# --- 音量正規化＆軽いEQ風処理 ---
final_audio = final_audio.apply_gain(-2.5)  # 全体音量調整
final_audio = final_audio.low_pass_filter(4000).high_pass_filter(250)  # 電話風EQ

# --- 書き出し ---
final_audio.export(str(OUTPUT_FILE), format="mp3", bitrate="192k")
print(f"✅ 完成: {OUTPUT_FILE}")

