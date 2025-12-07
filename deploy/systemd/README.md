# Gateway systemd サービス設定

## 概要

LibertyCall Gateway（realtime_gateway.py）を systemd サービスとして安定稼働させるための設定ファイルです。

## ファイル構成

- `gateway.service` - systemd ユニットファイル
- `../scripts/setup_gateway_service.sh` - サービス設定スクリプト
- `../scripts/watch_gateway_log.sh` - ログ監視スクリプト（cron 用）
- `../scripts/setup_gateway_cron.sh` - cron 設定スクリプト

## セットアップ手順

### 1. systemd サービスの設定

```bash
cd /workspace
sudo bash deploy/scripts/setup_gateway_service.sh
```

または手動で：

```bash
# systemd ユニットファイルをコピー
sudo cp deploy/systemd/gateway.service /etc/systemd/system/

# ログディレクトリを作成
sudo mkdir -p /opt/libertycall/logs
sudo chown liberty:liberty /opt/libertycall/logs

# systemd をリロード
sudo systemctl daemon-reload

# サービスを有効化・起動
sudo systemctl enable gateway.service
sudo systemctl restart gateway.service

# ステータス確認
sudo systemctl status gateway -n 20
```

### 2. ログ監視 cron の設定

```bash
cd /workspace
bash deploy/scripts/setup_gateway_cron.sh
```

または手動で：

```bash
# スクリプトに実行権限を付与
chmod +x deploy/scripts/watch_gateway_log.sh

# cron に登録
(crontab -l 2>/dev/null | grep -v "watch_gateway_log.sh" || true; \
 echo "* * * * * /opt/libertycall/scripts/watch_gateway_log.sh") | crontab -
```

## 設定内容

### systemd ユニットファイルの特徴

- **自動再起動**: `Restart=always` + `RestartSec=5` で5秒後に自動再起動
- **起動制限**: `StartLimitIntervalSec=60` + `StartLimitBurst=5` で1分間に5回以上再起動したら待機
- **ウォッチドッグ**: `WatchdogSec=30` で30秒応答がなければ強制再起動
- **ログ分離**: 標準出力と標準エラーを別ファイルに保存
- **即時ログ出力**: `PYTHONUNBUFFERED=1` でバッファリング無効化

### ログファイル

- `/opt/libertycall/logs/gateway_stdout.log` - 標準出力
- `/opt/libertycall/logs/gateway_stderr.log` - 標準エラー
- `/opt/libertycall/logs/gateway_watchdog.log` - 監視スクリプトのログ

## 動作確認

### サービスステータス確認

```bash
sudo systemctl status gateway
```

期待される出力：
```
Active: active (running)
```

### ログ確認

```bash
# 標準出力ログ
tail -f /opt/libertycall/logs/gateway_stdout.log

# エラーログ
tail -f /opt/libertycall/logs/gateway_stderr.log

# 監視ログ
tail -f /opt/libertycall/logs/gateway_watchdog.log
```

### 自動再起動のテスト

```bash
# サービスを停止
sudo systemctl stop gateway

# 5秒後に自動再起動されることを確認
sleep 6
sudo systemctl status gateway
```

## トラブルシューティング

### サービスが起動しない場合

1. ログを確認：
   ```bash
   sudo journalctl -u gateway -n 50
   ```

2. パスと権限を確認：
   ```bash
   ls -l /opt/libertycall/venv/bin/python3
   ls -l /opt/libertycall/gateway/realtime_gateway.py
   ```

3. ユーザー権限を確認：
   ```bash
   id liberty
   ```

### ログが出力されない場合

1. ログディレクトリの権限を確認：
   ```bash
   ls -ld /opt/libertycall/logs
   ```

2. サービスを再起動：
   ```bash
   sudo systemctl restart gateway
   ```

## 注意事項

- `liberty` ユーザーが存在しない場合は、ユーザー作成または `User=` 設定を変更してください
- ログファイルは自動的にローテーションされません。必要に応じて `logrotate` を設定してください
- `WatchdogSec` は Gateway が定期的に応答する必要があります。実装されていない場合は削除してください
