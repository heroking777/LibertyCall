# AI コーディング環境セットアップ手順書

## 📋 環境調査結果

### 現在の環境
- **OS**: Ubuntu 24.04.3 LTS (Linux)
- **デフォルトシェル**: bash (`/bin/bash`)
- **シェル設定ファイル**: `~/.bashrc`
- **Node.js**: v24.11.1 (nvm経由でインストール済み)
- **npm**: 11.6.2
- **nvm**: 0.39.7 (インストール済み)
- **Python**: 確認が必要（`python3 --version`で確認）
- **ブラウザ**: Chrome/Chromiumの確認が必要

### インストール済みツール
- ✅ nvm (Node Version Manager)
- ✅ Node.js v24.11.1
- ✅ GitHub Copilot CLI v0.1.36

---

## 🚀 セットアップ手順

### Step 1: 環境確認と準備

```bash
# 現在の環境を確認
echo "=== 環境確認 ==="
echo "OS: $(uname -s)"
echo "Shell: $SHELL"
echo "Node: $(node -v 2>/dev/null || echo '未インストール')"
echo "Python: $(python3 --version 2>/dev/null || echo '未インストール')"
echo "npm: $(npm -v 2>/dev/null || echo '未インストール')"

# nvmが読み込まれているか確認
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
echo "nvm: $(nvm --version 2>/dev/null || echo '未インストール')"
```

---

### Step 2: GitHub Copilot CLI セットアップ（ローカルPC用）

> **方針転換メモ**
> - VPS（/opt/libertycall）上での Copilot CLI 利用は DNS 制限で困難なため断念。
> - サーバ側に既に入っている `@githubnext/github-copilot-cli` は放置して問題ありません（`npm uninstall -g @githubnext/github-copilot-cli` で削除しても可）。
> - 以降は **ローカルPC（Mac もしくは Windows）に Copilot CLI を導入し、ブラウザ経由で認証して使う** 流れを前提とします。

#### 2.0 ローカルPCへの前提確認

ローカルで Terminal / PowerShell を開き、以下を実行してください。

```bash
# Node.js / npm の確認
node -v
npm -v

# nvm や volta を使っている場合は、普段どおり Node を有効化してから実行
```

バージョン表示が出ない場合は、[公式サイト](https://nodejs.org/) から LTS 版 (推奨: 18 以上) をインストールしてください。

#### 2.1 Copilot CLI のインストール（ローカル）

```bash
# macOS (bash/zsh) / Windows (PowerShell) 共通
npm install -g @githubnext/github-copilot-cli

# バージョン確認
github-copilot-cli --version
```

#### 2.2 ローカルでの認証手順

```bash
github-copilot-cli auth

# 画面に 8 桁コードが表示されるのでコピー
# ブラウザで https://github.com/login/device を開き、コードを貼り付ける
# 「Authorize GitHub Copilot CLI」を承認
# CLI に戻って成功メッセージが出れば完了
```


#### 2.3 動作確認コマンド例（ローカルで実行）

```bash
# OS 情報を AI に要約させる
github-copilot-cli what-the-shell "macOS でディスク空き容量を確認するコマンド"

# Git 操作の提案
github-copilot-cli git-assist "コミットログを見て 1 個前に戻す操作を教えて"

# GitHub CLI コマンド提案
github-copilot-cli gh-assist "Issues をラベル付きでフィルタする gh コマンドください"
```

> **Tips:** 既存のエイリアス（例: `ghcp-explain` など）をローカルPCの `~/.bashrc` / `~/.zshrc` / PowerShell プロファイルに追記すると扱いやすくなります。


---

### Step 3: Phind ブラウザショートカット設定

#### 3.1 Chrome/Chromiumの確認

```bash
# 利用可能なブラウザを確認
if command -v google-chrome &> /dev/null; then
    BROWSER="google-chrome"
elif command -v google-chrome-stable &> /dev/null; then
    BROWSER="google-chrome-stable"
elif command -v chromium &> /dev/null; then
    BROWSER="chromium"
elif command -v chromium-browser &> /dev/null; then
    BROWSER="chromium-browser"
else
    echo "⚠️  Chrome/Chromiumが見つかりません。手動でインストールしてください。"
    exit 1
fi

echo "使用するブラウザ: $BROWSER"
```

#### 3.2 デスクトップショートカット作成

```bash
# デスクトップアプリケーションディレクトリを作成
mkdir -p ~/.local/share/applications

# Phind用の.desktopファイルを作成
cat > ~/.local/share/applications/phind.desktop << EOF
[Desktop Entry]
Name=Phind
Comment=Phind AI コーディングアシスタント
Exec=$BROWSER --profile-directory=Default --app=https://www.phind.com/
Terminal=false
Type=Application
Icon=chrome
Categories=Development;Utility;
StartupWMClass=Phind
EOF

# 実行権限を付与
chmod +x ~/.local/share/applications/phind.desktop

echo "✅ Phind デスクトップショートカットを作成しました"
echo "   アプリケーションメニューから「Phind」を起動できます"
```

#### 3.3 ブラウザからPWAとしてインストール（推奨）

```bash
# ブラウザでPhindを開く
$BROWSER https://www.phind.com/

# ブラウザ内で以下を実行:
# 1. アドレスバー右側の「インストール」アイコンをクリック
# 2. または、メニュー（⋮）→「アプリケーションをインストール」を選択
```

#### 3.4 エイリアス設定（オプション）

```bash
# ~/.bashrcにPhind起動エイリアスを追加
cat >> ~/.bashrc << EOF

# Phind 起動エイリアス
alias phind='$BROWSER --profile-directory=Default --app=https://www.phind.com/'
EOF

source ~/.bashrc
```

---

### Step 4: Claude Workbench セットアップ

#### 4.1 プロジェクトディレクトリの作成

```bash
# Claude Workbench用のプロジェクトディレクトリを作成
mkdir -p ~/ClaudeProjects/main
cd ~/ClaudeProjects/main

# プレースホルダーファイルを作成（Git管理用）
touch .keep
echo "# Claude Workbench プロジェクト" > README.md
```

#### 4.2 環境変数ファイルの作成

```bash
# Claude API Key用の環境変数ファイルを作成
cat > ~/.claude.env << 'EOF'
# Claude API Key
# https://console.anthropic.com/ でAPI Keyを取得してください
export CLAUDE_API_KEY=""
EOF

echo "✅ ~/.claude.env を作成しました"
echo "   CLAUDE_API_KEY を設定してください"
```

#### 4.3 エイリアスと環境変数読み込み設定

```bash
# ~/.bashrcにClaude関連の設定を追加
cat >> ~/.bashrc << 'EOF'

# Claude Workbench 設定
export CLAUDE_WORKBENCH_URL="https://claude.ai/workbench"
export CLAUDE_PROJECTS_DIR="$HOME/ClaudeProjects"

# Claude環境変数を読み込み
[ -f ~/.claude.env ] && source ~/.claude.env

# Claude Workbench 起動エイリアス
alias claude='echo "Claude Workbench: $CLAUDE_WORKBENCH_URL" && xdg-open "$CLAUDE_WORKBENCH_URL" 2>/dev/null || echo "ブラウザで $CLAUDE_WORKBENCH_URL を開いてください"'
alias claude-projects='cd $CLAUDE_PROJECTS_DIR && ls -la'
EOF

source ~/.bashrc
```

#### 4.4 使用方法

```bash
# Claude Workbenchを開く
claude

# または、ブラウザで直接開く
xdg-open https://claude.ai/workbench

# プロジェクトディレクトリに移動
cd ~/ClaudeProjects/main

# ファイルをドラッグ&ドロップしてWorkbenchにアップロード
```

---

### Step 5: Gemini CLI セットアップ

#### 5.1 インストール

```bash
# nvmを読み込む
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# Gemini CLIがインストールされているか確認
if command -v gemini &> /dev/null; then
    echo "✅ Gemini CLI は既にインストール済みです"
    gemini --version
else
    echo "📦 Gemini CLI をインストールします..."
    npm install -g @google/generative-ai-cli
fi
```

#### 5.2 環境変数ファイルの作成

```bash
# Gemini API Key用の環境変数ファイルを作成
cat > ~/.gemini.env << 'EOF'
# Google Gemini API Key
# https://aistudio.google.com/app/apikey でAPI Keyを取得してください
export GEMINI_API_KEY=""
EOF

echo "✅ ~/.gemini.env を作成しました"
echo "   GEMINI_API_KEY を設定してください"
```

#### 5.3 認証

```bash
# Gemini環境変数を読み込み
[ -f ~/.gemini.env ] && source ~/.gemini.env

# Gemini CLIでログイン（API Keyを設定）
if [ -z "$GEMINI_API_KEY" ]; then
    echo "⚠️  GEMINI_API_KEY が設定されていません"
    echo "   ~/.gemini.env にAPI Keyを設定してから gemini login を実行してください"
else
    gemini login
fi
```

#### 5.4 エイリアス設定

```bash
# ~/.bashrcにGemini関連の設定を追加
cat >> ~/.bashrc << 'EOF'

# Gemini CLI 設定
export GEMINI_SAMPLES_DIR="$HOME/gemini-samples"

# Gemini環境変数を読み込み
[ -f ~/.gemini.env ] && source ~/.gemini.env

# Gemini CLI エイリアス
alias gsum='gemini read --summary'
alias gerr='gemini read --grep ERROR'
alias gread='gemini read'
EOF

# サンプルディレクトリを作成
mkdir -p ~/gemini-samples
touch ~/gemini-samples/.keep

source ~/.bashrc
```

---

### Step 6: 全体的なエイリアス整理

```bash
# ~/.bashrcに全体的なAIツールエイリアスを追加
cat >> ~/.bashrc << 'EOF'

# ============================================
# AI コーディングツール エイリアス集
# ============================================

# GitHub Copilot CLI
alias ai='github-copilot-cli'
alias ghcp='github-copilot-cli'
alias ghcp-explain='github-copilot-cli what-the-shell'
alias ghcp-git='github-copilot-cli git-assist'
alias ghcp-gh='github-copilot-cli gh-assist'

# Phind
alias phind='google-chrome --profile-directory=Default --app=https://www.phind.com/ 2>/dev/null || chromium --app=https://www.phind.com/ 2>/dev/null || echo "ブラウザが見つかりません"'

# Claude Workbench
alias claude='xdg-open https://claude.ai/workbench 2>/dev/null || echo "ブラウザで https://claude.ai/workbench を開いてください"'
alias claude-projects='cd $CLAUDE_PROJECTS_DIR && ls -la'

# Gemini CLI
alias gsum='gemini read --summary'
alias gerr='gemini read --grep ERROR'
alias gread='gemini read'

# 環境変数読み込み
[ -f ~/.claude.env ] && source ~/.claude.env
[ -f ~/.gemini.env ] && source ~/.gemini.env

# 便利な関数
ai-help() {
    echo "=== AI コーディングツール ヘルプ ==="
    echo ""
    echo "GitHub Copilot CLI:"
    echo "  ghcp-explain 'コマンド説明'  - シェルコマンドを説明"
    echo "  ghcp-git 'git操作'           - Gitコマンドを生成"
    echo "  ghcp-gh 'GitHub操作'         - GitHub CLIコマンドを生成"
    echo ""
    echo "Phind:"
    echo "  phind                        - Phindを開く"
    echo ""
    echo "Claude Workbench:"
    echo "  claude                       - Claude Workbenchを開く"
    echo "  claude-projects              - プロジェクトディレクトリに移動"
    echo ""
    echo "Gemini CLI:"
    echo "  gsum <file>                  - ファイルの要約"
    echo "  gerr <file>                  - エラーログを抽出"
    echo "  gread <file>                 - ファイルを読み込む"
}
EOF

source ~/.bashrc
```

---

### Step 7: 「ローカル Copilot CLI × サーバ MCP」ワークフロー

> 目的： `/opt/libertycall` のソースコードをローカルにクローンし、ローカルでは Copilot CLI を活用、VPS ではこれまで通り MCP（Claude Workbench など）を利用する二段構え。

#### 7.1 リポジトリの取得（ローカルPC上で実行）

```bash
# ローカルで作業用ディレクトリを作成
mkdir -p ~/workspace && cd ~/workspace

# /opt/libertycall のリポジトリを clone
git clone <YOUR_GIT_REMOTE_URL> libertycall
cd libertycall

# 例: VSCode などローカルエディタで開く
code .
```

> `YOUR_GIT_REMOTE_URL` は GitHub / GitLab など実際のリモート URL に置き換えてください。  
> 以後はローカルで編集＆Copilot CLI に相談しつつ、完成した変更を Git commit → push。

#### 7.2 ローカルでの Copilot CLI 活用例

```bash
# ローカルリポジトリ直下で
ghcp-explain "gateway/realtime_gateway.py のログ周り整理計画を提案して"
ghcp-git "現在の差分をまとめてコミットする手順を教えて"
```

#### 7.3 サーバ側（/opt/libertycall）では MCP を継続利用

- VPS は引き続き Claude Workbench / Gemini CLI / Phind PWA など MCP ベースの運用が可能。
- サーバで実行結果やログを取得 → `~/ClaudeProjects/main` に必要ファイルをコピーしてアップロード → Claude と議論。
- コード修正はローカルで行い、`git push` した内容をサーバで pull・デプロイする流れが推奨。

この構成で「Copilot CLI はローカルのデスクトップ環境で」「サーバは MCP + 実行環境」と役割を分担できます。

---

## ✅ テストコマンド

すべてのセットアップが完了したら、以下のコマンドで動作確認してください：

```bash
# 新しいシェルを開くか、設定を再読み込み
source ~/.bashrc

# 1. GitHub Copilot CLI
echo "=== GitHub Copilot CLI テスト ==="
github-copilot-cli --version
ghcp-explain "現在のディレクトリのファイル一覧を表示"

# 2. Phind
echo ""
echo "=== Phind テスト ==="
echo "phind コマンドを実行してブラウザが開くか確認"
# phind  # コメントを外して実行

# 3. Claude Workbench
echo ""
echo "=== Claude Workbench テスト ==="
echo "Claude Workbench URL: $CLAUDE_WORKBENCH_URL"
claude-projects
# claude  # コメントを外して実行

# 4. Gemini CLI
echo ""
echo "=== Gemini CLI テスト ==="
if command -v gemini &> /dev/null; then
    gemini --version
    gemini --help
    echo "テストファイルを作成..."
    echo "これはテストログです。ERROR: サンプルエラー" > ~/gemini-samples/test.log
    echo "要約テスト:"
    gsum ~/gemini-samples/test.log
    echo "エラー抽出テスト:"
    gerr ~/gemini-samples/test.log
else
    echo "⚠️  Gemini CLI がインストールされていません"
fi

# 5. エイリアス確認
echo ""
echo "=== エイリアス確認 ==="
ai-help
```

---

## 📝 API Key 設定方法

### Claude API Key

1. https://console.anthropic.com/ にアクセス
2. アカウントを作成/ログイン
3. API Keys セクションで新しいキーを作成
4. `~/.claude.env` を編集して設定：

```bash
nano ~/.claude.env
# または
vim ~/.claude.env

# CLAUDE_API_KEY="your-api-key-here" を設定
```

### Gemini API Key

1. https://aistudio.google.com/app/apikey にアクセス
2. Googleアカウントでログイン
3. 「Create API Key」をクリック
4. `~/.gemini.env` を編集して設定：

```bash
nano ~/.gemini.env
# または
vim ~/.gemini.env

# GEMINI_API_KEY="your-api-key-here" を設定
```

設定後、新しいシェルを開くか `source ~/.bashrc` を実行してください。

---

## 🔧 トラブルシューティング

### Node.js/npmが見つからない

```bash
# nvmを読み込む
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# Node.jsをインストール（まだの場合）
nvm install --lts
nvm use --lts
```

### コマンドが見つからない

```bash
# PATHを確認
echo $PATH

# npmのグローバルパスを確認
npm config get prefix

# 必要に応じてPATHに追加
export PATH="$(npm config get prefix)/bin:$PATH"
```

### ブラウザが開かない

```bash
# xdg-openの代わりに直接ブラウザを指定
google-chrome https://claude.ai/workbench
# または
chromium https://claude.ai/workbench
```

### 環境変数が読み込まれない

```bash
# ~/.bashrcを再読み込み
source ~/.bashrc

# または、新しいシェルを開く
bash -l
```

---

## 📚 使用方法の例

### GitHub Copilot CLI

```bash
# シェルコマンドの説明を取得
ghcp-explain "dockerコンテナを一覧表示して、停止中のものを削除"

# Git操作のコマンドを生成
ghcp-git "最後のコミットを修正してメッセージを変更"

# GitHub CLIコマンドを生成
ghcp-gh "新しいissueを作成してラベルを付ける"
```

### Claude Workbench

```bash
# プロジェクトディレクトリに移動
cd ~/ClaudeProjects/main

# ファイルをコピーしてWorkbenchにドラッグ&ドロップ
cp /path/to/your/file.py ~/ClaudeProjects/main/

# Workbenchを開く
claude
```

### Gemini CLI

```bash
# ログファイルの要約
gsum /var/log/app.log

# エラーログを抽出
gerr /var/log/app.log

# コードファイルを読み込んで分析
gread src/main.py
```

---

## 🎉 セットアップ完了

すべてのセットアップが完了しました！

次回からは、新しいターミナルを開くと自動的にすべてのツールが利用可能になります。

ヘルプを表示するには：
```bash
ai-help
```

---

**生成日時**: $(date)
**環境**: Ubuntu 24.04.3 LTS
**Node.js**: v24.11.1
**npm**: 11.6.2

