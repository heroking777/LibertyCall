# 法人向けメールアドレス収集バッチシステム

日本国内の法人の公式サイトから、公開されている代表メールアドレスを収集するバッチシステムです。

## ⚠️ 重要な注意事項

**本システムは、法人の公式サイトに公開されている情報のみを収集します。**

- 個人事業主・個人クリニック・個人の士業事務所は除外されます
- フリーメールアドレス（gmail.com / yahoo.co.jp / outlook.com 等）は除外されます
- 患者専用・予約専用・採用専用のメールアドレスは除外されます
- ログインが必要なサイトや、利用規約上スクレイピングを禁止しているサイトを積極的に狙い撃ちしません
- **公開された法人の連絡先のみを対象とし、個人情報や非公開情報の収集は行いません**

## 対象業種

1. 医療法人（医療法人・医療法人社団・医療法人財団など）
2. 美容医療（医療法人または株式会社運営の美容クリニック等）
3. 不動産会社
4. 工務店・リフォーム会社
5. 介護施設（社会福祉法人・医療法人・株式会社運営の法人施設）
6. 士業法人（税理士法人・社労士法人・司法書士法人など）

## セットアップ

### 1. 必要な環境

- Python 3.11以上
- Linux環境（ConoHa VPS等を想定）

### 2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 3. 設定ファイルの作成

#### 3.1 Google Custom Search Engine (CSE) の設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. Custom Search API を有効化
3. [Custom Search Engine](https://programmablesearchengine.google.com/controlpanel/create) で検索エンジンを作成
4. APIキーと検索エンジンIDを取得

#### 3.2 OpenAI API の設定

1. [OpenAI Platform](https://platform.openai.com/) でアカウントを作成
2. APIキーを生成

#### 3.3 設定ファイルの作成

```bash
# 設定ファイルの例をコピー
cp config/settings.example.toml config/settings.toml

# エディタで編集
nano config/settings.toml
```

`config/settings.toml` に以下を設定してください：

```toml
[google_cse]
# ⚠️ 重要: APIキーは環境変数から読み込みます
# 環境変数 GOOGLE_CSE_API_KEY を設定するか、.envファイルに追加してください
api_key = ""  # 環境変数 GOOGLE_CSE_API_KEY から読み込む
search_engine_id = "55f13fd11267244ba"
daily_query_limit = 100

[openai]
api_key = "YOUR_OPENAI_API_KEY"
model = "gpt-4o-mini"
```

#### 3.4 クエリファイルの作成（オプション）

```bash
# クエリファイルの例をコピー
cp config/queries.example.txt config/queries.txt

# 必要に応じて編集
nano config/queries.txt
```

`config/queries.txt` が存在しない場合は、`config/queries.example.txt` が自動的に使用されます。

### 4. .gitignore の設定（推奨）

```bash
# .gitignore に追加
echo "config/settings.toml" >> .gitignore
echo "data/" >> .gitignore
```

## 使用方法

### 基本的な実行

```bash
python -m src.main
```

### オプション

```bash
# カスタム設定ファイルを指定
python -m src.main --config config/custom_settings.toml

# カスタムクエリファイルを指定
python -m src.main --queries config/custom_queries.txt

# 最大URL数を制限（テスト用）
python -m src.main --max-urls 10

# ドライラン（実際には保存しない）
python -m src.main --dry-run
```

### シェルスクリプトからの実行

```bash
chmod +x scripts/run_once.sh
./scripts/run_once.sh
```

## 定期実行（cron設定）

1日1回、自動的に実行する場合のcron設定例：

```bash
# crontabを編集
crontab -e

# 毎日午前2時に実行する例
0 2 * * * /opt/libertycall/corp_collector/scripts/run_once.sh >> /opt/libertycall/corp_collector/data/logs/cron.log 2>&1
```

## 出力ファイル

### CSV形式（デフォルト）

`data/output/leads_YYYYMMDD.csv` に以下のカラムで保存されます：

- `email`: メールアドレス
- `company_name`: 会社名
- `address`: 所在地
- `website_url`: 元のURL
- `industry`: 業種
- `domain`: ドメイン
- `source`: ソース識別子（"auto_batch"）
- `created_at`: 作成日時（ISO 8601形式）

### SQLite形式

`config/settings.toml` で `format = "sqlite"` に設定すると、SQLiteデータベースに保存されます。

```toml
[output]
format = "sqlite"
```

## ログ

ログファイルは `data/logs/app_YYYYMMDD.log` に日毎に保存されます。

ログレベルは `config/settings.toml` の `[log].level` で設定できます。

## プロジェクト構成

```
corp_collector/
├── config/
│   ├── settings.example.toml    # 設定ファイルの例
│   └── queries.example.txt      # クエリファイルの例
├── src/
│   ├── __init__.py
│   ├── main.py                  # エントリーポイント
│   ├── cse_client.py            # Google CSE クライアント
│   ├── fetcher.py               # HTML取得
│   ├── extractor.py             # OpenAI情報抽出
│   ├── storage.py               # データ保存
│   ├── logging_config.py        # ログ設定
│   └── utils.py                 # ユーティリティ
├── data/
│   ├── output/                  # 出力ファイル
│   └── logs/                    # ログファイル
├── scripts/
│   └── run_once.sh              # 実行スクリプト
├── requirements.txt
└── README.md
```

## トラブルシューティング

### Google CSE API のエラー

- APIキーと検索エンジンIDが正しく設定されているか確認
- 無料枠（100クエリ/日）を超えていないか確認
- レートリミットエラーが発生した場合は、処理が自動的に中断されます

### OpenAI API のエラー

- APIキーが正しく設定されているか確認
- APIの利用制限に達していないか確認
- レートリミットエラーが発生した場合は、自動的にリトライされます

### HTML取得のエラー

- ネットワーク接続を確認
- タイムアウト設定を調整（`config/settings.toml` の `[crawler].request_timeout_seconds`）

## ライセンス

このプロジェクトは内部使用を目的としています。

## コンプライアンス

本システムは、以下の方針に従って運用してください：

1. **公開情報のみを対象**: 法人の公式サイトに公開されている情報のみを収集します
2. **個人情報の除外**: 個人事業主や個人の連絡先は除外されます
3. **適切な利用**: 収集した情報は適切に管理し、法令を遵守して利用してください
4. **利用規約の遵守**: 各サイトの利用規約を確認し、スクレイピングが禁止されている場合は対象外とします

