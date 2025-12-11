#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_tree.txt から構造情報を抽出して project_states.json の structure フィールドを更新するスクリプト

使い方:
    python scripts/sync_project_structure.py

動作:
    1. docs/project_tree.txt を読み込む
    2. 主要ディレクトリ/ファイルとその用途を抽出
    3. project_states.json の各プロジェクトの structure フィールドを更新
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
PROJECT_TREE_FILE = PROJECT_ROOT / "docs" / "project_tree.txt"
PROJECT_STATES_FILE = PROJECT_ROOT / "project_states.json"


def parse_project_tree(content: str) -> Dict[str, str]:
    """
    project_tree.txt から構造情報を抽出
    
    フォーマット例:
        ├── README.md                                    # プロジェクト概要・セットアップ手順
        ├── gateway/                                     # リアルタイム音声処理
        └── console_backend/                            # 管理画面API
    
    Returns:
        Dict[str, str]: {パス: 用途} の辞書
    """
    structure = {}
    lines = content.split('\n')
    
    # 主要なディレクトリ/ファイルのパターン（ルートレベル）
    # セクション区切り（[XXX]）の直下の項目のみを抽出
    in_section = False
    current_section = None
    
    for line in lines:
        # セクション区切り（[XXX]）を検出
        section_match = re.match(r'^├──\s+\[([^\]]+)\]\s*$', line)
        if section_match:
            in_section = True
            current_section = section_match.group(1).strip()
            continue
        
        # セクション内の項目を抽出
        if in_section:
            # ├── または └── で始まる行を検索
            match = re.search(r'[├└]──\s+([^\s#]+)\s+#\s+(.+)', line)
            if match:
                path = match.group(1).strip()
                purpose = match.group(2).strip()
                
                # インデントレベルで判定（先頭の空白数をカウント）
                indent_level = len(line) - len(line.lstrip())
                
                # セクション直下の項目のみ（インデントが少ない）
                if indent_level <= 8:  # ├── [XXX] の下の項目
                    # ディレクトリの場合は末尾の / を削除
                    if path.endswith('/'):
                        path = path[:-1]
                    
                    # 主要なディレクトリ/ファイルのみを抽出
                    # （node_modules, venv, dist, build などは除外）
                    if path and not any(skip in path for skip in ['node_modules', 'venv', '__pycache__', '.git', 'dist/', 'build/']):
                        # セクション名をパスに含める（例: "gateway/" → "gateway/"）
                        structure[path] = purpose
        
        # ルートレベルのファイル（セクション外）も抽出
        if not in_section:
            match = re.search(r'^├──\s+([^\s#]+)\s+#\s+(.+)', line)
            if match:
                path = match.group(1).strip()
                purpose = match.group(2).strip()
                
                # ディレクトリの場合は末尾の / を削除
                if path.endswith('/'):
                    path = path[:-1]
                
                # 主要なファイルのみを抽出
                if path and not any(skip in path for skip in ['node_modules', 'venv', '__pycache__', '.git']):
                    structure[path] = purpose
    
    return structure


def update_project_states(structure: Dict[str, str], project_id: str = "ai-phone-main") -> bool:
    """
    project_states.json の指定プロジェクトの structure フィールドを更新
    
    Args:
        structure: 構造情報の辞書
        project_id: 更新するプロジェクトID
    
    Returns:
        bool: 更新が成功したかどうか
    """
    try:
        # 既存の project_states.json を読み込む
        if PROJECT_STATES_FILE.exists():
            with open(PROJECT_STATES_FILE, 'r', encoding='utf-8') as f:
                states = json.load(f)
        else:
            states = {}
        
        # 指定プロジェクトが存在しない場合は作成
        if project_id not in states:
            print(f"警告: プロジェクト '{project_id}' が存在しません。新規作成します。")
            states[project_id] = {
                "projectId": project_id,
                "name": project_id,
                "type": "ai_phone",
                "summary": "",
                "techStack": [],
                "status": "in_progress",
                "currentFocus": "",
                "tasks": [],
                "decisions": [],
                "issues": [],
                "importantFiles": [],
                "updatedAt": ""
            }
        
        # structure フィールドを更新
        states[project_id]["structure"] = structure
        
        # 更新時刻を更新
        from datetime import datetime, timezone
        states[project_id]["updatedAt"] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # ファイルに保存
        with open(PROJECT_STATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(states, f, ensure_ascii=False, indent=2)
        
        print(f"✅ プロジェクト '{project_id}' の structure フィールドを更新しました。")
        print(f"   更新された項目数: {len(structure)}")
        return True
        
    except Exception as e:
        print(f"❌ エラー: project_states.json の更新に失敗しました: {e}")
        return False


def main():
    """メイン処理"""
    print("=" * 60)
    print("project_tree.txt から構造情報を抽出して project_states.json を更新")
    print("=" * 60)
    
    # project_tree.txt を読み込む
    if not PROJECT_TREE_FILE.exists():
        print(f"❌ エラー: {PROJECT_TREE_FILE} が見つかりません。")
        sys.exit(1)
    
    print(f"📖 {PROJECT_TREE_FILE} を読み込んでいます...")
    with open(PROJECT_TREE_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 構造情報を抽出
    print("🔍 構造情報を抽出しています...")
    structure = parse_project_tree(content)
    
    if not structure:
        print("⚠️  警告: 構造情報が抽出できませんでした。")
        sys.exit(1)
    
    print(f"✅ {len(structure)} 個の項目を抽出しました。")
    
    # project_states.json を更新
    print(f"📝 project_states.json を更新しています...")
    success = update_project_states(structure)
    
    if success:
        print("=" * 60)
        print("✅ 更新完了！")
        print("=" * 60)
        sys.exit(0)
    else:
        print("=" * 60)
        print("❌ 更新失敗")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()

