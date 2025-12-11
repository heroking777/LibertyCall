# プロジェクト構造自動同期スクリプト

`docs/project_tree.txt` が更新されたら、自動的に `project_states.json` の `structure` フィールドを更新する仕組みです。

## ファイル

- `sync_project_structure.py`: `project_tree.txt` から構造情報を抽出して `project_states.json` を更新
- `watch_project_tree.py`: `project_tree.txt` の変更を監視して自動更新（オプション）
- `.git/hooks/post-commit`: Git commit 後に自動更新（オプション）

## 使い方

### 手動実行

```bash
python3 scripts/sync_project_structure.py
```

### ファイル監視（自動実行）

```bash
# バックグラウンドで実行
python3 scripts/watch_project_tree.py &

# または systemd サービスとして実行
# （systemd サービス設定例は scripts/ ディレクトリを参照）
```

### Git hook（自動実行）

Git commit 時に `project_tree.txt` が変更されていたら自動的に更新されます。

```bash
# Git hook が有効になっているか確認
ls -la .git/hooks/post-commit

# 手動で実行（テスト用）
.git/hooks/post-commit
```

## 動作

1. `docs/project_tree.txt` を読み込む
2. 主要ディレクトリ/ファイルとその用途を抽出
3. `project_states.json` の各プロジェクトの `structure` フィールドを更新

## 抽出される情報

- ルートレベルのファイル（例: `README.md`, `requirements.txt`）
- 主要ディレクトリ（例: `gateway/`, `console_backend/`, `libertycall/`）
- セクション内の主要項目（例: `[Gateway - リアルタイム音声処理]` セクション内の項目）

## 除外される項目

- `node_modules/`, `venv/`, `__pycache__/`, `.git/` などの自動生成ディレクトリ
- `dist/`, `build/` などのビルド成果物
- サブディレクトリ内の詳細なファイル（主要なもののみ）

## トラブルシューティング

### 項目数が多すぎる場合

`sync_project_structure.py` の `parse_project_tree()` 関数でフィルタリング条件を調整してください。

### ファイル監視が動作しない場合

`watchdog` パッケージがインストールされているか確認してください：

```bash
pip install watchdog
```

### Git hook が動作しない場合

`.git/hooks/post-commit` に実行権限があるか確認してください：

```bash
chmod +x .git/hooks/post-commit
```

