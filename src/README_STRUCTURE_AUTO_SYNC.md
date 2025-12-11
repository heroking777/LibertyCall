# 構造情報自動同期機能

ファイルシステムをスキャンして、`project_states.json` の `structure` フィールドを自動更新する機能です。

## 機能

- **ファイルシステムスキャン**: 実際のディレクトリ構造をスキャン
- **差分検出**: 保存されている構造情報と実際の構造を比較
- **自動更新**: 差分があれば自動的に `project_states.json` を更新
- **差分ログ**: 変更内容を `logs/structure_diff.log` に記録
- **除外リスト**: `node_modules`, `venv` などの自動生成ディレクトリを除外

## 使い方

### 1. 手動実行（API経由）

```bash
# 自動同期を有効にしてプロジェクト一覧を取得
curl "http://localhost:3000/projects?sync=true"

# 自動同期を有効にしてプロジェクト状態を取得
curl "http://localhost:3000/projects/ai-phone-main/state?sync=true"
```

### 2. 環境変数で有効化

```bash
# 起動時に自動同期
export AUTO_SYNC_ON_START=true

# 定期自動同期（10分ごと）
export SYNC_INTERVAL_MINUTES=10

# 常に自動同期（listProjects/getProjectState 実行時）
export AUTO_SYNC_STRUCTURE=true

# プロジェクトルートディレクトリ（デフォルト: プロジェクトルート）
export PROJECT_ROOT=/opt/libertycall
```

### 3. systemd サービス設定例

```ini
[Service]
Environment="AUTO_SYNC_ON_START=true"
Environment="SYNC_INTERVAL_MINUTES=30"
Environment="PROJECT_ROOT=/opt/libertycall"
```

## 除外パターン

以下のディレクトリ/ファイルは自動的に除外されます：

- `node_modules/`
- `venv/`
- `__pycache__/`
- `.git/`
- `dist/`, `build/`
- `.next/`, `.vscode/`, `.idea/`
- `*.log`, `*.pyc`
- `.env`, `.DS_Store`

## 差分ログ

変更が検出されると、`logs/structure_diff.log` に以下の形式で記録されます：

```json
{
  "timestamp": "2025-12-05T12:00:00.000Z",
  "projectId": "ai-phone-main",
  "added": 5,
  "removed": 2,
  "changed": 1,
  "details": {
    "added": {
      "new_file.py": "Pythonスクリプト",
      "new_dir/": "ディレクトリ"
    },
    "removed": {
      "old_file.py": "Pythonスクリプト"
    },
    "changed": {
      "updated_file.md": {
        "old": "Markdownドキュメント",
        "new": "プロジェクト概要・セットアップ手順"
      }
    }
  }
}
```

## パフォーマンス

- スキャン深度: 最大5階層まで（パフォーマンス向上のため）
- 非同期処理: 自動同期は非同期で実行され、API応答をブロックしません
- 差分検出: 変更がある場合のみ更新（無駄な書き込みを防止）

## トラブルシューティング

### スキャンが遅い場合

- スキャン深度を調整: `structureAutoSync.ts` の `walk()` 関数の `depth` 制限を変更
- 除外パターンを追加: `EXCLUDE_PATTERNS` に追加のパターンを追加

### ログファイルが作成されない場合

- `logs/` ディレクトリの権限を確認
- 手動で `logs/` ディレクトリを作成

### 自動同期が動作しない場合

- 環境変数が正しく設定されているか確認
- サーバーのログを確認（`journalctl -u libertycall-projects.service -f`）

