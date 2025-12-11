# 自動メール送信システム

LibertyCallの自動メール送信システムです。AWS SESを使用してメールを送信し、APSchedulerで定期実行を管理します。

## 機能

- **自動メール送信**: 初回メールとフォローアップメール（3回）を自動送信
- **スケジュール管理**: APSchedulerを使用した定期実行
- **配信停止機能**: 配信停止リストによる自動除外
- **CSV管理**: 送信先リストをCSVファイルで管理

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
DAILY_SEND_LIMIT=100
SENDER_EMAIL=info@libcall.com

# フォローアップ間隔（日数）
FOLLOWUP1_DAYS_AFTER=7
FOLLOWUP2_DAYS_AFTER=7
FOLLOWUP3_DAYS_AFTER=7

# スケジュール設定（オプション）
EMAIL_SEND_HOUR=9      # 送信時刻（時、デフォルト: 9）
EMAIL_SEND_MINUTE=0    # 送信時刻（分、デフォルト: 0）
```

### 3. 送信先リストの準備

`recipients.csv`に送信先を追加：

```csv
id,email,name,stage,initial_sent_at,followup1_sent_at,followup2_sent_at,followup3_sent_at,last_sent_at
1,user1@example.com,ユーザー1,initial,,,,,
2,user2@example.com,ユーザー2,initial,,,,,
```

## 使用方法

### 手動実行（1回のみ送信）

```bash
cd /opt/libertycall
source venv/bin/activate
python -m email_sender.main
```

### スケジューラーサービスとして実行（定期実行）

```bash
cd /opt/libertycall
source venv/bin/activate
python -m email_sender.scheduler_service
```

このコマンドを実行すると、毎日指定時刻（デフォルト: 9:00）に自動でメール送信が実行されます。

### systemdサービスとして実行

`/etc/systemd/system/email-sender.service`を作成：

```ini
[Unit]
Description=LibertyCall Email Sender Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/libertycall
Environment="PATH=/opt/libertycall/venv/bin"
ExecStart=/opt/libertycall/venv/bin/python -m email_sender.scheduler_service
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

サービスを有効化：

```bash
sudo systemctl daemon-reload
sudo systemctl enable email-sender.service
sudo systemctl start email-sender.service
sudo systemctl status email-sender.service
```

## ファイル構成

```
email_sender/
├── __init__.py
├── config.py              # 設定管理
├── models.py              # データモデル
├── csv_repository.py      # CSV操作・配信停止チェック
├── ses_client.py          # AWS SES送信
├── scheduler.py           # 送信タイミング判定
├── scheduler_service.py   # APSchedulerサービス
├── main.py                # エントリーポイント（手動実行用）
└── templates/             # メールテンプレート
    ├── initial_email.txt
    ├── followup_1.txt
    ├── followup_2.txt
    └── followup_3.txt
```

## 動作フロー

1. **送信先リスト読み込み**: `recipients.csv`から送信先を読み込む
2. **配信停止チェック**: `unsubscribe_list.csv`に含まれるメールアドレスを除外
3. **送信タイミング判定**: 各レシピエントのステージと送信日時を確認
4. **メール送信**: AWS SES経由でメールを送信
5. **送信履歴更新**: 送信日時をCSVに記録

## 配信停止機能

配信停止は`/lp/unsubscribe`ページから実行できます。

配信停止されたメールアドレスは`unsubscribe_list.csv`に記録され、以降の自動送信から除外されます。

## ログ

スケジューラーサービスは標準出力にログを出力します。systemdサービスとして実行する場合、`journalctl`で確認できます：

```bash
sudo journalctl -u email-sender.service -f
```

## トラブルシューティング

### メールが送信されない

1. AWS認証情報が正しく設定されているか確認
2. SESで送信元メールアドレスが検証済みか確認
3. 送信先リストに有効なメールアドレスが含まれているか確認
4. 配信停止リストに含まれていないか確認

### スケジューラーが動作しない

1. 環境変数`EMAIL_SEND_HOUR`と`EMAIL_SEND_MINUTE`が正しく設定されているか確認
2. システム時刻が正しいか確認
3. ログを確認してエラーがないか確認

