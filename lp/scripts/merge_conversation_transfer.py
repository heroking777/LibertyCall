#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LibertyCall デモ音声合成スクリプト（パターン3：担当者への転送）
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
CUSTOMER_PATH = AUDIO_DIR / "12月13日（20-45）.m4a"
AI_VOICE_FILES = [
    "ai_voice_transfer_01.mp3",
    "ai_voice_transfer_02.mp3",
    "ai_voice_transfer_03.mp3",
    "ai_voice_transfer_04.mp3",
]
OUTPUT_FILE = AUDIO_DIR / "demo_transfer.mp3"

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
print("\n▶ 会話形式で合成中...")

# 人間の音声を4つのセクションに分割（AI音声の数に合わせる）
customer_sections = []

# 人間の音声をAI音声の間に入れるように分割
section_durations = [
    customer_duration * 0.33,  # 最初の応答（長め - AI音声2の前に人間が話し終わるように）
    customer_duration * 0.40,  # 2番目（さらに長め - AI音声3の前に人間が話し終わるように）
    customer_duration * 0.17,  # 3番目（転送待ち中）
    customer_duration * 0.10,  # 最後（余り - セクション2を延長した分を調整）
]

# 最初のセクションは無音をスキップ
initial_silence_skip = 1000  # 1秒
cursor = initial_silence_skip if initial_silence_skip < len(customer) else 0

for i, duration in enumerate(section_durations):
    end_pos = min(cursor + int(duration * 1000), len(customer))
    section = customer[cursor:end_pos]
    
    # 各セクションの先頭の無音を削除
    silence_threshold = -50  # dB
    chunk_length = 50  # ms
    start_pos = 0
    
    # 最初のセクションは1秒後から、セクション2は積極的に無音削除、それ以外は3秒までチェック
    if i == 0:
        check_range = 1000
    elif i == 1:
        # セクション2は無音が長いので、積極的に削除（セクション全体をチェック）
        check_range = len(section)
    else:
        check_range = 3000
    
    for chunk_start in range(0, min(len(section), check_range), chunk_length):
        chunk = section[chunk_start:chunk_start + chunk_length]
        if chunk.dBFS > silence_threshold:
            start_pos = chunk_start
            break
    
    if start_pos > 0:
        section = section[start_pos:]
        print(f"  人間セクション{i+1}の先頭{start_pos/1000:.2f}秒の無音を削除")
    
    if i == 0:
        print(f"  人間セクション1: 最初の1秒をスキップして開始")
    
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
        final_audio += AudioSegment.silent(duration=100)  # 間を短く

# --- 音量正規化＆軽いEQ風処理 ---
final_audio = final_audio.apply_gain(-2.5)  # 全体音量調整
final_audio = final_audio.low_pass_filter(4000).high_pass_filter(250)  # 電話風EQ

# --- 書き出し ---
final_audio.export(str(OUTPUT_FILE), format="mp3", bitrate="192k")
print(f"✅ 完成: {OUTPUT_FILE}")

