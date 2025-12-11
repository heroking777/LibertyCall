#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音声検証を実行して結果を表示するスクリプト"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path("/opt/libertycall")
sys.path.insert(0, str(PROJECT_ROOT))

# 認証情報を設定
cred_path = PROJECT_ROOT / "key" / "google_tts.json"
if cred_path.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path)

# 検証スクリプトをインポート
from scripts.sync_voice_assets import (
    load_voice_lines,
    get_audio_files,
    find_mismatches,
    TEMPLATE_CONFIG,
    verify_audio_content,
    calculate_similarity
)

def main():
    print("=" * 80)
    print("クライアント000 音声ファイルと音声リストの検証")
    print("=" * 80)
    print()
    
    # データ読み込み
    print("📖 データ読み込み中...")
    template_config = TEMPLATE_CONFIG
    voice_lines = load_voice_lines()
    audio_files = get_audio_files()
    
    template_ids = set(template_config.keys())
    voice_ids = set(voice_lines.keys())
    
    print(f"  - intent_rules.py テンプレート数: {len(template_ids)}")
    print(f"  - voice_lines_000.json テンプレート数: {len(voice_ids)}")
    print(f"  - 音声ファイル数: {len(audio_files)}")
    print()
    
    # テキスト不一致検出
    print("🔍 テキスト不一致検出中...")
    mismatches = find_mismatches(template_config, voice_lines)
    missing_audio = template_ids - audio_files
    orphan_audio = audio_files - template_ids
    
    print(f"\n📊 検証結果:")
    print(f"  - テキスト不一致: {len(mismatches)}件")
    print(f"  - 不足音声ファイル: {len(missing_audio)}件")
    print(f"  - 孤立音声ファイル: {len(orphan_audio)}件")
    print()
    
    # テキスト不一致の詳細
    if mismatches:
        print("⚠️ テキスト不一致の詳細:")
        for tid in sorted(mismatches.keys())[:10]:
            old_text, new_text = mismatches[tid]
            print(f"\n  テンプレート {tid}:")
            print(f"    voice_lines_000.json: {old_text}")
            print(f"    intent_rules.py:      {new_text}")
        if len(mismatches) > 10:
            print(f"\n  ... 他 {len(mismatches) - 10}件")
        print()
    
    # 不足音声ファイル
    if missing_audio:
        print(f"⚠️ 不足音声ファイル ({len(missing_audio)}件):")
        for tid in sorted(missing_audio)[:20]:
            text = template_config.get(tid, {}).get('text', 'N/A')
            print(f"  - template_{tid}.wav: {text[:60]}...")
        if len(missing_audio) > 20:
            print(f"  ... 他 {len(missing_audio) - 20}件")
        print()
    else:
        print("✅ すべてのテンプレートに対応する音声ファイルが存在します")
        print()
    
    # 孤立音声ファイル
    if orphan_audio:
        print(f"⚠️ 孤立音声ファイル ({len(orphan_audio)}件):")
        for tid in sorted(orphan_audio)[:10]:
            print(f"  - template_{tid}.wav")
        if len(orphan_audio) > 10:
            print(f"  ... 他 {len(orphan_audio) - 10}件")
        print()
    
    # 音声内容検証（音声ファイルが存在する場合）
    if audio_files:
        print("🎤 音声内容検証を実行しますか？ (y/n): ", end="")
        try:
            response = input().strip().lower()
        except:
            response = 'n'
        
        if response == 'y':
            print("\n🎤 音声内容検証中...")
            audio_mismatches = verify_audio_content(template_config, audio_files, similarity_threshold=0.8)
            
            if audio_mismatches:
                print(f"\n⚠️ 音声内容不一致 ({len(audio_mismatches)}件):")
                for tid, expected, detected, similarity in audio_mismatches:
                    print(f"\n  template_{tid}.wav (一致率: {similarity:.2f})")
                    print(f"    期待: {expected}")
                    print(f"    検出: {detected}")
            else:
                print("\n✅ すべての音声内容が一致しています。")
        else:
            print("\nℹ️ 音声内容検証をスキップしました。")
    
    print("\n" + "=" * 80)
    print("検証完了")
    print("=" * 80)

if __name__ == "__main__":
    main()
