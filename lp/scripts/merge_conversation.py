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
# AI音声4（12月15日ですね）の前の人間セクション3を長めに調整
# 人間セクション1は雑音を避けるため1秒短く
# 人間セクション4は時間を言った後の応答なので長めに（AI音声5の前に人間が話し終わるように）
section_durations = [
    max(customer_duration * 0.11, 3.0),  # 最初の応答（1秒短縮: 0.14 → 0.11、最低3秒）
    customer_duration * 0.11,  # 2番目
    customer_duration * 0.18,  # 3番目（長め - AI音声4の前に人間が話し終わるように）
    customer_duration * 0.15,  # 4番目（長め - AI音声5の前に人間が話し終わるように）
    customer_duration * 0.12,  # 5番目（短め）
    customer_duration * 0.10,  # 6番目
    customer_duration * 0.23,  # 最後（長め）
]

# 最初のセクションは3秒後から開始（無音をスキップ）
initial_silence_skip = 3000  # 3秒
cursor = initial_silence_skip if initial_silence_skip < len(customer) else 0

for i, duration in enumerate(section_durations):
    end_pos = min(cursor + int(duration * 1000), len(customer))
    section = customer[cursor:end_pos]
    
    # 最初のセクションの先頭の無音をさらに削除
    if i == 0:
        # 先頭の無音を検出して削除
        silence_threshold = -50  # dB
        chunk_length = 50  # ms
        start_pos = 0
        # 最初の1秒をチェック
        for chunk_start in range(0, min(len(section), 1000), chunk_length):
            chunk = section[chunk_start:chunk_start + chunk_length]
            if chunk.dBFS > silence_threshold:
                start_pos = chunk_start
                break
        if start_pos > 0:
            section = section[start_pos:]
            print(f"  人間セクション1の先頭{start_pos/1000:.2f}秒の無音を削除")
        print(f"  人間セクション1: 最初の3秒をスキップして開始")
    
    customer_sections.append(section)
    cursor = end_pos
    print(f"  人間セクション{i+1}: {len(section)/1000:.2f}秒")

# 会話形式で合成: AI → 人間 → AI → 人間 → ...
final_audio = AudioSegment.silent(duration=0)

for i in range(len(ai_segments)):
    # AI音声を追加
    print(f"  AI音声{i+1}を追加...")
    final_audio += ai_segments[i]
    
    # 最初のAI音声の後は無音を完全に削除、それ以外は100ms
    if i > 0:
        final_audio += AudioSegment.silent(duration=100)
    
    # 人間の応答を追加
    if i < len(customer_sections):
        print(f"  人間応答{i+1}を追加...")
        final_audio += customer_sections[i]
        final_audio += AudioSegment.silent(duration=100)  # 間を短く（300ms → 100ms）

# --- 音量正規化＆軽いEQ風処理 ---
final_audio = final_audio.apply_gain(-2.5)  # 全体音量調整
final_audio = final_audio.low_pass_filter(4000).high_pass_filter(250)  # 電話風EQ

# --- 書き出し ---
final_audio.export(str(OUTPUT_FILE), format="mp3", bitrate="192k")
print(f"✅ 完成: {OUTPUT_FILE}")

