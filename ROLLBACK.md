# ロールバック手順（bypass-media実装前に戻す）

## 現在のコミット（バックアップポイント）
- **日時**: 2025-12-29 06:35:01
- **コミットハッシュ**: 8e31b94
- **メッセージ**: 🤖 Auto commit by AI 2025-12-29 06:35:01

## 重要：ローカルバックアップのみ
- GitHubへのプッシュは秘密情報（google-credentials.json）のためブロックされています
- **ローカルの191コミットがバックアップです**

## 戻し方

### 1. 最新のバックアップコミットに戻す
```bash
cd /opt/libertycall
git log --oneline -20  # バックアップコミットを確認

# bypass-media実装前（このファイル作成時点）に戻す場合：
git reset --hard 8e31b94
```

### 2. サービス再起動
```bash
sudo systemctl restart libertycall.service
sudo systemctl restart freeswitch.service
```

### 3. 動作確認
```bash
sudo journalctl -u libertycall.service -f
```

## 注意事項
- このコミット以降の変更は全て失われます
- 必要なファイルは事前にコピーしてください
- ローカルのgitリポジトリを削除しないでください（バックアップが失われます）

## bypass-media実装後にプッシュする場合
秘密情報を除外してからプッシュする必要があります：
1. `config/google-credentials.json`を`.gitignore`に追加
2. 履歴から削除: `git filter-branch`または`git filter-repo`を使用
