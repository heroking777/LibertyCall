#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEMPLATE_CONFIG と voice_lines_000.json の差分チェックスクリプト

使い方:
    python scripts/check_template_voice_diff.py
"""

import json
import sys
from pathlib import Path

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# TEMPLATE_CONFIG をインポート
try:
    from libertycall.gateway.common.text_utils import TEMPLATE_CONFIG
except ImportError:
    try:
        from gateway.text_utils import TEMPLATE_CONFIG
    except ImportError:
        print("ERROR: intent_rules.py から TEMPLATE_CONFIG をインポートできませんでした。")
        sys.exit(1)

# voice_lines_000.json を読み込む
VOICE_LINES_JSON = PROJECT_ROOT / "clients" / "000" / "config" / "voice_lines_000.json"

def main():
    """メイン処理"""
    print("=" * 60)
    print("TEMPLATE_CONFIG と voice_lines_000.json の差分チェック")
    print("=" * 60)
    print()
    
    # voice_lines_000.json を読み込む
    if not VOICE_LINES_JSON.exists():
        print(f"ERROR: {VOICE_LINES_JSON} が見つかりません。")
        sys.exit(1)
    
    with open(VOICE_LINES_JSON, 'r', encoding='utf-8') as f:
        voice_lines = json.load(f)
    
    # テンプレートIDのセットを取得
    template_config_ids = set(TEMPLATE_CONFIG.keys())
    voice_lines_ids = {k for k in voice_lines.keys() if k != 'voice'}
    
    # 差分を計算
    only_in_template = template_config_ids - voice_lines_ids
    only_in_voice_lines = voice_lines_ids - template_config_ids
    common_ids = template_config_ids & voice_lines_ids
    
    # 結果を表示
    print(f"TEMPLATE_CONFIG のテンプレート数: {len(template_config_ids)}")
    print(f"voice_lines_000.json のテンプレート数: {len(voice_lines_ids)}")
    print(f"共通テンプレート数: {len(common_ids)}")
    print()
    
    # TEMPLATE_CONFIG にあるが voice_lines_000.json にない ID
    if only_in_template:
        print(f"⚠ voice_lines_000.json に追加が必要な ID ({len(only_in_template)}件):")
        for tid in sorted(only_in_template, key=lambda x: (len(x), x)):
            cfg = TEMPLATE_CONFIG[tid]
            print(f"  - {tid}: {cfg.get('text', '')[:50]}...")
        print()
    else:
        print("✓ voice_lines_000.json に不足している ID はありません。")
        print()
    
    # voice_lines_000.json にあるが TEMPLATE_CONFIG にない ID
    if only_in_voice_lines:
        print(f"⚠ TEMPLATE_CONFIG に存在しない ID ({len(only_in_voice_lines)}件):")
        for tid in sorted(only_in_voice_lines, key=lambda x: (len(x), x)):
            if tid == 'voice':
                continue
            vline = voice_lines[tid]
            print(f"  - {tid}: {vline.get('text', '')[:50]}...")
        print()
    else:
        print("✓ TEMPLATE_CONFIG に不足している ID はありません。")
        print()
    
    # 共通IDの text の差分チェック
    text_diff_count = 0
    for tid in sorted(common_ids, key=lambda x: (len(x), x)):
        template_text = TEMPLATE_CONFIG[tid].get("text", "")
        voice_text = voice_lines[tid].get("text", "")
        if template_text != voice_text:
            text_diff_count += 1
            if text_diff_count <= 5:  # 最初の5件だけ表示
                print(f"  ⚠ {tid}: text が異なります")
                print(f"    TEMPLATE_CONFIG: {template_text[:60]}...")
                print(f"    voice_lines_000.json: {voice_text[:60]}...")
    
    if text_diff_count > 5:
        print(f"  ... 他 {text_diff_count - 5} 件の text 差分があります")
    
    if text_diff_count == 0:
        print("✓ 共通IDの text はすべて一致しています。")
    else:
        print(f"⚠ {text_diff_count} 件の text 差分があります。")
    print()
    
    # サマリー
    print("=" * 60)
    print("サマリー")
    print("=" * 60)
    print(f"追加が必要: {len(only_in_template)} 件")
    print(f"TEMPLATE_CONFIG に存在しない: {len(only_in_voice_lines)} 件")
    print(f"text 差分: {text_diff_count} 件")
    print()
    
    if only_in_template:
        print("→ voice_lines_000.json に以下の ID を追加してください:")
        print(f"   {', '.join(sorted(only_in_template, key=lambda x: (len(x), x)))}")
        print()


if __name__ == "__main__":
    main()

