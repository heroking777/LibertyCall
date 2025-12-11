#!/bin/bash
# 毎日本リストに新しいデータを追記するスクリプト

# スクリプトのディレクトリに移動
cd "$(dirname "$0")/.." || exit 1

# Pythonスクリプトを実行（今日の日付のファイルを自動検出）
python3 scripts/append_to_master.py

