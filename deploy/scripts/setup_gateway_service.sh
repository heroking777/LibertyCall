#!/bin/bash
# Gateway systemd サービス設定スクリプト
# このスクリプトを実行すると、gateway.service を設定し、有効化します

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_FILE="gateway.service"
SOURCE_FILE="$PROJECT_ROOT/deploy/systemd/$SERVICE_FILE"

echo "=== LibertyCall Gateway Service セットアップ ==="

# 1. systemd ユニットファイルをコピー
if [ ! -f "$SOURCE_FILE" ]; then
    echo "エラー: $SOURCE_FILE が見つかりません"
    exit 1
fi

echo "1. systemd ユニットファイルをコピー中..."
sudo cp "$SOURCE_FILE" "$SYSTEMD_DIR/$SERVICE_FILE"
sudo chmod 644 "$SYSTEMD_DIR/$SERVICE_FILE"

# 2. ログディレクトリを作成
echo "2. ログディレクトリを作成中..."
sudo mkdir -p /opt/libertycall/logs
sudo chown liberty:liberty /opt/libertycall/logs || echo "警告: liberty ユーザーが存在しない可能性があります"

# 3. systemd をリロード
echo "3. systemd をリロード中..."
sudo systemctl daemon-reload

# 4. サービスを有効化
echo "4. サービスを有効化中..."
sudo systemctl enable gateway.service

# 5. サービスを起動
echo "5. サービスを起動中..."
sudo systemctl restart gateway.service

# 6. ステータス確認
echo ""
echo "=== サービスステータス ==="
sudo systemctl status gateway.service -n 20 --no-pager

echo ""
echo "=== ログ確認 ==="
echo "標準出力ログ: /opt/libertycall/logs/gateway_stdout.log"
echo "エラーログ: /opt/libertycall/logs/gateway_stderr.log"
echo ""
echo "ログ監視コマンド:"
echo "  tail -f /opt/libertycall/logs/gateway_stdout.log"
echo "  tail -f /opt/libertycall/logs/gateway_stderr.log"
echo ""
echo "=== セットアップ完了 ==="
