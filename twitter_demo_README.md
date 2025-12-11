# Twitter/X Automation Scraper Demo

最小限のデモスクリプト - Python + Playwrightを使用してTwitter/Xからコメントを抽出します。

## 機能

- `cookies.json`からTwitterクッキーを読み込み
- ヘッドレスモードでTwitterにアクセス
- 指定されたプロフィールの最新ツイートを開く
- コメント（返信）を抽出
- 過去10日以内のコメントのみをフィルタリング
- 結果をCSVファイルに保存

## セットアップ

### 1. 仮想環境のアクティベート

```bash
# 既存のvenvを使用する場合
source venv/bin/activate

# または、新しいvenvを作成する場合
python3 -m venv venv
source venv/bin/activate
```

### 2. 依存関係のインストール

```bash
# requirements.txtからインストール（推奨）
pip install -r requirements.txt

# または、playwrightのみインストール
pip install playwright
```

### 3. Playwrightブラウザのインストール

```bash
# 仮想環境内で実行
playwright install chromium
```

### 3. クッキーの設定

`cookies.json`ファイルを編集して、実際のTwitterクッキーを設定してください。

**クッキーの取得方法:**

1. ブラウザでTwitterにログイン
2. 開発者ツール（F12）を開く
3. Application/Storageタブ → Cookies → https://twitter.com
4. 以下のクッキーをコピー:
   - `auth_token` (最重要)
   - `ct0` (CSRFトークン)
   - `twid` (ユーザーID)

`cookies.json`の例:

```json
[
  {
    "name": "auth_token",
    "value": "実際のトークン値",
    "domain": ".twitter.com",
    "path": "/",
    "expires": -1,
    "httpOnly": true,
    "secure": true,
    "sameSite": "None"
  }
]
```

## 実行

### 方法1: 実行スクリプトを使用（推奨）

```bash
./run_demo.sh
```

### 方法2: 手動で実行

```bash
# 仮想環境をアクティベートしてから実行
source venv/bin/activate
python demo.py
```

## 出力

結果は `demo_output.csv` に保存されます:

```csv
username,text,timestamp
user1,コメントテキスト,2024-01-15T10:30:00Z
user2,別のコメント,2024-01-16T14:20:00Z
```

## 設定

`demo.py`の先頭で以下の設定を変更できます:

- `TARGET_PROFILE`: ターゲットプロフィール名（デフォルト: "elonmusk"）
- `DAYS_THRESHOLD`: フィルタリングする日数（デフォルト: 10日）
- `OUTPUT_FILE`: 出力ファイル名（デフォルト: "demo_output.csv"）

## 注意事項

- このスクリプトはデモ用です。本番環境では適切なエラーハンドリングとレート制限を実装してください
- TwitterのDOM構造は頻繁に変わるため、セレクタが機能しない場合があります
- クッキーは定期的に更新する必要があります
- Twitterの利用規約を遵守してください

## トラブルシューティング

### クッキーが無効な場合

- ブラウザで再度ログインしてクッキーを更新してください
- `auth_token`が正しく設定されているか確認してください

### コメントが抽出されない場合

- ツイートにコメント（返信）が存在するか確認してください
- ページの読み込み時間を増やす（`page.wait_for_timeout()`の値を増やす）
- TwitterのDOM構造が変更された可能性があります

### ヘッドレスモードで問題が発生する場合

一時的にヘッドレスモードを無効にしてデバッグ:

```python
browser = p.chromium.launch(headless=False)
```

