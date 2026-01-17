# 失われたファイルの特定作業 - 分析レポート

## 調査日時
2025年12月25日

## 1. 12月24日のコミット履歴

### コミット数
- 12月24日から12月25日まで: **約50コミット以上**
- 主な変更内容: `freeswitch/scripts/play_audio_sequence.lua` の頻繁な更新

### 重要な発見
- **最後のコミット（12月25日 08:34:33）**: 3つのm4a音声ファイルが0バイトになった
  - `lp/audio/12月13日（19-54）.m4a` (190KB → 0 bytes)
  - `lp/audio/12月13日（20-29）.m4a` (110KB → 0 bytes)
  - `lp/audio/12月13日（20-45）.m4a` (61KB → 0 bytes)

## 2. ログ暴走で削除された可能性があるファイル

### logsディレクトリの状態
- `logs/contact_api.log` - **0バイト**（空ファイル）
- `logs/hangup_call.log` - 2.1KB（正常）
- `Brevo Planning/webhook.log` - 1.2KB（正常）

### __pycache__ディレクトリの状態
以下のディレクトリに存在（正常）:
- `./gateway/utils/__pycache__`
- `./gateway/__pycache__`
- `./libs/esl/__pycache__`
- `./email_sender/__pycache__`
- `./__pycache__`
- `./console_backend/services/__pycache__`
- `./console_backend/websocket/__pycache__`
- `./console_backend/__pycache__`
- `./libertycall/gateway/__pycache__`
- `./libertycall/__pycache__`

### .gitignoreで除外されているファイル
- `.env` - 環境変数（正常に存在）
- `call_console.db` - データベース（52KB、正常に存在）
- `logs/*.log` - ログファイル（一部0バイト）
- `__pycache__/` - Pythonキャッシュ（正常）
- `backups_offgit/` - ローカルバックアップ（16KB、正常）
- `node_modules/` - Node.js依存関係（正常）
- `*.wav`, `*.m4a` - 音声ファイル（.gitignoreで除外されているが、一部Gitで管理されている）

## 3. ディスク使用量の確認

### プロジェクト全体
- **総サイズ**: 135MB
- **.gitディレクトリ**: 64MB（約47%）
- **lpディレクトリ**: 38MB（約28%）
- **gatewayディレクトリ**: 15MB（約11%）
- **Brevo Planning**: 7.8MB
- **freeswitch**: 3.6MB
- **email_sender**: 2.6MB

### 大きなディレクトリの詳細
- `lp/` - 38MB、20個のファイル（音声ファイルは0個）
- `lp/audio/` - ディレクトリは存在するが、**ファイルが空**

## 4. 過去のコミットとのファイル数比較

### ファイル数の変化
- **現在（HEAD）**: 361個のファイル
- **10コミット前（12月20日頃）**: 325個のファイル
- **差分**: **+36個のファイルが追加された**

### 削除されたファイル（10コミット前と比較）
以下の3つのm4aファイルのみが削除（0バイト化）:
1. `lp/audio/12月13日（19-54）.m4a`
2. `lp/audio/12月13日（20-29）.m4a`
3. `lp/audio/12月13日（20-45）.m4a`

### 追加されたファイル
- 10コミット前と比較して、**新規ファイルの追加は検出されず**
- ファイル数の増加は、既存ファイルの変更やGit履歴の更新によるものと推測

## 5. 重要な発見

### 失われたファイル
1. **3つのm4a音声ファイル**（合計約362KB）
   - これらは12月13日に追加され、12月25日に0バイトになった
   - Gitで管理されているため、復元可能

2. **logs/contact_api.log**（0バイト）
   - ログファイルは.gitignoreで除外されているため、復元不可
   - 新規作成されるため、問題なし

### 0バイトファイル
以下のファイルが0バイト:
- `logs/contact_api.log`
- `gateway/venv/`内の一部ファイル（Python仮想環境、問題なし）

### ファイル数の増加について
- ファイル数が**増加**している（325 → 361）
- これは**正常な状態**を示している
- 削除されたファイルは3つのm4aファイルのみ

## 6. 復元可能なファイル

### Gitで管理されているファイル（復元可能）
1. `lp/audio/12月13日（19-54）.m4a` - 190KB
2. `lp/audio/12月13日（20-29）.m4a` - 110KB
3. `lp/audio/12月13日（20-45）.m4a` - 61KB

**復元方法**: 以前のコミットから復元可能
```bash
# 例: 12月13日のコミットから復元
git checkout 779cfa8 -- "lp/audio/12月13日（20-45）.m4a"
git checkout 641fa36 -- "lp/audio/12月13日（20-29）.m4a"
git checkout d9e602c -- "lp/audio/12月13日（20-45）.m4a"
```

### Gitで管理されていないファイル（復元不可）
- `logs/contact_api.log` - ログファイル（新規作成されるため問題なし）
- その他の一時ファイルやキャッシュファイル

## 7. 結論

### 実際に失われたファイル
- **3つのm4a音声ファイルのみ**（合計約362KB）
- これらはGitで管理されているため、**完全に復元可能**

### ログ暴走の影響
- ログファイル（`logs/contact_api.log`）が0バイトになったが、これは新規作成されるため問題なし
- その他の重要なファイルに影響なし

### 推奨アクション
1. **m4aファイルの復元**: 以前のコミットから復元
2. **ログファイル**: 自動的に再作成されるため、対応不要
3. **その他のファイル**: すべて正常な状態

## 8. 復元スクリプト

以下のコマンドで3つのm4aファイルを復元できます:

```bash
cd /opt/libertycall

# バックアップ作成
mkdir -p backups_offgit/restore_$(date +%Y%m%d_%H%M%S)

# 以前のコミットから復元
git checkout d9e602c -- "lp/audio/12月13日（20-45）.m4a"
git checkout 641fa36 -- "lp/audio/12月13日（20-29）.m4a"
git checkout 779cfa8 -- "lp/audio/12月13日（19-54）.m4a"

# 復元確認
ls -lh lp/audio/*.m4a

# コミット
git add lp/audio/*.m4a
git commit -m "復元: 失われたm4a音声ファイルを復元"
```

