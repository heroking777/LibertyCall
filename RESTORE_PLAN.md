# GitHubバックアップからのファイル復元プラン

## 現状確認結果

### 1. Gitリポジトリの状態
- **リポジトリパス**: `/opt/libertycall`
- **リモートURL**: `https://github.com/heroking777/LibertyCall.git`
- **現在のブランチ**: `main`
- **ローカルとリモートの同期状態**: ✅ 同期済み（差分なし）
- **Working tree**: ✅ Clean（未コミットの変更なし）
- **最後のコミット**: `908390c 🤖 Auto commit by AI 2025-12-25 08:34:33`

### 2. ファイル構成
- **Gitで管理されているファイル数**: 361個
- **実際のファイル数（.gitignore除外）**: 約1,974個
- **未追跡ファイル**: 0個（すべて.gitignoreで適切に除外されている）
- **プロジェクトサイズ**: 約135MB

### 3. 重要なファイルの存在確認
✅ `.env` - 存在（.gitignoreで除外、ローカルのみ）
✅ `.env.example` - Gitで管理されている
✅ `package.json` - 存在
✅ `alembic.ini` - 存在
✅ `config/` ディレクトリ - 存在
✅ 主要なPythonスクリプト - 存在

### 4. 最近の変更履歴
- 最後の10コミットはすべて正常な自動コミット
- 最近のコミットで3つのm4a音声ファイルが0バイトになった（意図的な削除の可能性）
- その他の重要なファイルに問題なし

### 5. バックアップ対象外のファイル（保持すべき）
以下のファイルはGitで管理されていないため、復元後も保持が必要：
- `.env` - 環境変数設定（ローカルのみ）
- `call_console.db` - ローカルデータベース（52KB）
- `logs/*.log` - ログファイル
- `__pycache__/` - Pythonキャッシュ
- `backups_offgit/` - ローカルバックアップ
- `clients/*/audio/` - クライアント音声ファイル
- `*.wav`, `*.m4a` - 音声ファイル（生成物）

## 復元プラン提案

### 結論
**現在のGitリポジトリは正常な状態です。ローカルとリモートは完全に同期しており、ファイルが失われた形跡はありません。**

ただし、以下のいずれかの状況が考えられます：
1. Gitで管理されていないファイル（.gitignoreで除外されている）が失われた
2. 特定のディレクトリのファイルが失われた
3. 以前のバージョンに戻したい

### オプションA: 最新状態の確認（推奨）
**目的**: リモートの最新状態を確認し、必要に応じて更新

```bash
cd /opt/libertycall
git fetch origin
git status
git log origin/main -5 --oneline
```

**メリット**: 
- 安全（既存ファイルを変更しない）
- 現在の状態を確認できる

**デメリット**: 
- ファイルは復元されない（既に同期済みのため）

### オプションB: 完全リセット（注意が必要）
**目的**: リモートの状態に完全に合わせる

```bash
cd /opt/libertycall
# 現在の.envをバックアップ
cp .env .env.backup
# リモートの状態に完全リセット
git fetch origin
git reset --hard origin/main
# .envを復元
cp .env.backup .env
```

**メリット**: 
- リモートと完全に一致する
- ローカルの変更をすべて破棄

**デメリット**: 
- ローカルの未コミット変更が失われる
- .envなどのローカルファイルは手動で復元が必要

### オプションC: 特定のファイル/ディレクトリのみ復元
**目的**: 特定のファイルだけを以前のバージョンから復元

```bash
cd /opt/libertycall
# 例: 特定のファイルを以前のコミットから復元
git checkout HEAD~5 -- path/to/file.py
```

**メリット**: 
- 選択的に復元できる
- 他のファイルに影響しない

**デメリット**: 
- どのファイルを復元すべきか特定が必要

### オプションD: 新規クローン（最終手段）
**目的**: 完全にクリーンな状態から開始

```bash
# 現在のディレクトリをバックアップ
mv /opt/libertycall /opt/libertycall.backup
# 新規クローン
cd /opt
git clone https://github.com/heroking777/LibertyCall.git
# 必要なローカルファイルをコピー
cp /opt/libertycall.backup/.env /opt/libertycall/
cp /opt/libertycall.backup/call_console.db /opt/libertycall/ 2>/dev/null || true
```

**メリット**: 
- 完全にクリーンな状態
- 確実にリモートと一致

**デメリット**: 
- 手順が複雑
- ローカルファイルの手動復元が必要

## 推奨アクション

### ステップ1: 詳細な状況確認
失われたと感じている具体的なファイルやディレクトリを特定してください。

### ステップ2: 復元方法の選択
上記のオプションから最適な方法を選択してください。

### ステップ3: 実行前のバックアップ
どの方法を選択しても、実行前に以下をバックアップ：
```bash
cd /opt/libertycall
# .envのバックアップ
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
# データベースのバックアップ
cp call_console.db call_console.db.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
```

## 実行前の確認事項

### 保持すべきファイル
- [ ] `.env` - 環境変数設定
- [ ] `call_console.db` - ローカルデータベース
- [ ] `backups_offgit/` - ローカルバックアップ
- [ ] `clients/*/config/*.bak` - クライアント設定のバックアップ
- [ ] その他のローカルで生成されたファイル

### 再設定が必要な可能性があるファイル
- `.env` - 環境変数の確認
- `config/gateway.yaml` - ゲートウェイ設定
- `config/client_mapping.json` - クライアントマッピング
- systemdサービスファイル（`deploy/systemd/`）

## 次のステップ

1. **失われたファイルの特定**: 具体的にどのファイルが失われたか教えてください
2. **復元方法の選択**: 上記のオプションから選択してください
3. **承認後の実行**: 選択した方法を実行します

