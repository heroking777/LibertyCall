# 営業メール自動送信システム（本番仕様）

LibertyCallの営業メール自動送信システムの本番仕様です。

## 主な機能

- **1日200件上限送信**
- **スケジューラー（APScheduler）で毎朝9:00自動実行**
- **送信成功後にCSVへstageとlast_sent_dateを更新**
- **unsubscribeリスト除外対応**
- **シミュレーションモード**（SES承認前でも動作確認可能）

## セットアップ

### 1. 依存パッケージのインストール

```bash
cd /opt/libertycall
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env`ファイルに以下を設定：

```bash
# AWS設定
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key

# 送信設定
DAILY_SEND_LIMIT=200
SENDER_EMAIL=sales@libcall.com

# スケジュール設定（オプション）
EMAIL_SEND_HOUR=9      # 送信時刻（時、デフォルト: 9）
EMAIL_SEND_MINUTE=0    # 送信時刻（分、デフォルト: 0）
```

### 3. 送信先リストの準備

`recipients.csv`に送信先を追加（サンプル: `recipients_sample.csv`を参照）：

```csv
company_name,contact_name,email,phone,industry,prefecture,stage,last_sent_date
株式会社アルファ,田中太郎,tanaka@example.com,03-1111-2222,IT,東京,initial,
株式会社ベータ,佐藤花子,sato@example.com,06-3333-4444,製造,大阪,initial,
```

## 使用方法

### シミュレーションモード（テスト用）

SES承認前でも動作確認できます。実際にはメールを送信しません。

#### 手動実行（1回のみ、10件まで）

```bash
cd /opt/libertycall
source venv/bin/activate
python -m email_sender.run_batch --simulation
```

#### スケジューラーサービスとして実行

```bash
python -m email_sender.scheduler_service_prod --simulation
```

### 本番モード

#### 手動実行（1回のみ）

```bash
python -m email_sender.run_batch
```

#### スケジューラーサービスとして実行（定期実行）

```bash
python -m email_sender.scheduler_service_prod
```

このコマンドを実行すると、毎日指定時刻（デフォルト: 9:00）に自動でメール送信が実行されます。

### systemdサービスとして実行

`/etc/systemd/system/email-sender-prod.service`を作成：

```ini
[Unit]
Description=LibertyCall Email Sender Service (Production)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/libertycall
Environment="PATH=/opt/libertycall/venv/bin"
ExecStart=/opt/libertycall/venv/bin/python -m email_sender.scheduler_service_prod
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

サービスを有効化：

```bash
sudo systemctl daemon-reload
sudo systemctl enable email-sender-prod.service
sudo systemctl start email-sender-prod.service
sudo systemctl status email-sender-prod.service
```

## ステージ管理

メール送信のステージは以下のように進行します：

1. **initial**: 初回メール
2. **follow1**: フォローアップ1回目
3. **follow2**: フォローアップ2回目
4. **follow3**: フォローアップ3回目
5. **completed**: 完了（以降は送信しない）

各ステージは3日間隔で送信されます（`SEND_INTERVAL_DAYS = 3`）。

## 配信停止機能

配信停止は`/lp/unsubscribe`ページから実行できます。

配信停止されたメールアドレスは`unsubscribe_list.csv`に記録され、以降の自動送信から除外されます。

## ログ

スケジューラーサービスは標準出力にログを出力します。systemdサービスとして実行する場合、`journalctl`で確認できます：

```bash
sudo journalctl -u email-sender-prod.service -f
```

## トラブルシューティング

### メールが送信されない

1. AWS認証情報が正しく設定されているか確認
2. SESで送信元メールアドレスが検証済みか確認
3. 送信先リストに有効なメールアドレスが含まれているか確認
4. 配信停止リストに含まれていないか確認
5. 送信間隔（3日）が経過しているか確認

### シミュレーションモードでテスト

SES承認前でも、シミュレーションモードで動作確認できます：

```bash
python -m email_sender.run_batch --simulation --limit 10
```

## ファイル構成

```
email_sender/
├── scheduler_service_prod.py  # 本番用スケジューラーサービス
├── csv_repository_prod.py     # 本番用CSVリポジトリ
├── run_batch.py               # 手動実行用スクリプト
├── recipients_sample.csv      # 送信先リストのサンプル
└── README_PROD.md             # このファイル
```

