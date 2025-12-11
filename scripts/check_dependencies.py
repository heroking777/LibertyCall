#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音声検証機能に必要な依存関係をチェックするスクリプト"""

import sys

missing = []

# Google Cloud Speech-to-Text
try:
    from google.cloud import speech
    print("✅ google-cloud-speech: インストール済み")
except ImportError:
    print("❌ google-cloud-speech: 未インストール")
    missing.append("google-cloud-speech")

# fuzzywuzzy
try:
    from fuzzywuzzy import fuzz
    print("✅ fuzzywuzzy: インストール済み")
except ImportError:
    print("⚠️ fuzzywuzzy: 未インストール（difflibで代替可能）")

# python-Levenshtein (fuzzywuzzyの高速化用)
try:
    import Levenshtein
    print("✅ python-Levenshtein: インストール済み")
except ImportError:
    print("⚠️ python-Levenshtein: 未インストール（fuzzywuzzyが遅くなる可能性）")

if missing:
    print("\n📦 インストールコマンド:")
    print(f"pip install {' '.join(missing)}")
    if "fuzzywuzzy" not in [m for m in missing]:
        print("pip install fuzzywuzzy python-Levenshtein")
    sys.exit(1)
else:
    print("\n✅ すべての依存関係がインストールされています。")
    sys.exit(0)
