#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project_tree.txt の変更を監視して、自動的に project_states.json を更新するスクリプト

使い方:
    python scripts/watch_project_tree.py

動作:
    1. docs/project_tree.txt の変更を監視
    2. 変更を検出したら自動的に sync_project_structure.py を実行
"""

import subprocess
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# プロジェクトルートのパスを取得
PROJECT_ROOT = Path(__file__).parent.parent
PROJECT_TREE_FILE = PROJECT_ROOT / "docs" / "project_tree.txt"
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync_project_structure.py"


class ProjectTreeHandler(FileSystemEventHandler):
    """project_tree.txt の変更を監視するハンドラ"""
    
    def __init__(self):
        self.last_modified = 0
        self.debounce_time = 2  # 2秒間のデバウンス
    
    def on_modified(self, event):
        """ファイル変更時の処理"""
        if event.src_path == str(PROJECT_TREE_FILE):
            # デバウンス処理（連続した変更を1回だけ処理）
            current_time = time.time()
            if current_time - self.last_modified < self.debounce_time:
                return
            
            self.last_modified = current_time
            print(f"\n📝 {PROJECT_TREE_FILE} が変更されました。")
            print("🔄 project_states.json を更新しています...")
            
            # sync_project_structure.py を実行
            try:
                result = subprocess.run(
                    [sys.executable, str(SYNC_SCRIPT)],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    print("✅ 更新完了！")
                else:
                    print(f"❌ 更新失敗: {result.stderr}")
            except Exception as e:
                print(f"❌ エラー: {e}")


def main():
    """メイン処理"""
    print("=" * 60)
    print("project_tree.txt の変更を監視中...")
    print(f"監視ファイル: {PROJECT_TREE_FILE}")
    print("=" * 60)
    print("Ctrl+C で終了します。")
    print()
    
    # ファイル監視の設定
    event_handler = ProjectTreeHandler()
    observer = Observer()
    observer.schedule(event_handler, path=str(PROJECT_TREE_FILE.parent), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n監視を終了します。")
        observer.stop()
    
    observer.join()


if __name__ == "__main__":
    # watchdog がインストールされているか確認
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("❌ エラー: watchdog がインストールされていません。")
        print("   インストール方法: pip install watchdog")
        sys.exit(1)
    
    main()

