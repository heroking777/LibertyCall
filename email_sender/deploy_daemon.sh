#!/bin/bash

# 24時間分散送信デーモン展開スクリプト

set -e

PROJECT_ROOT="/opt/libertycall"
DAEMON_NAME="continuous_sender"
PID_FILE="/var/run/${DAEMON_NAME}.pid"
LOG_FILE="/var/log/${DAEMON_NAME}.log"

echo "=== 24時間分散送信デーモン展開 ==="

# 必要なディレクトリを作成
sudo mkdir -p /var/log/libertycall
sudo chown deploy:deploy /var/log/libertycall

# systemdサービスファイルを作成
sudo tee /etc/systemd/system/${DAEMON_NAME}.service > /dev/null <<EOF
[Unit]
Description=LibertyCall Continuous Email Sender
After=network.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=${PROJECT_ROOT}
Environment=PATH=${PROJECT_ROOT}/.venv/bin
ExecStart=${PROJECT_ROOT}/.venv/bin/python -m email_sender.continuous_sender 5000
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10
TimeoutStopSec=60
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

# セキュリティ設定
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${PROJECT_ROOT}/email_sender/logs ${PROJECT_ROOT}/email_sender/data ${PROJECT_ROOT}/logs /var/log/libertycall ${PROJECT_ROOT}/email_sender

[Install]
WantedBy=multi-user.target
EOF

# systemdをリロード
sudo systemctl daemon-reload

# サービスを有効化
sudo systemctl enable ${DAEMON_NAME}

echo "=== 展開完了 ==="
echo "サービス名: ${DAEMON_NAME}"
echo "起動コマンド: sudo systemctl start ${DAEMON_NAME}"
echo "停止コマンド: sudo systemctl stop ${DAEMON_NAME}"
echo "ステータス確認: sudo systemctl status ${DAEMON_NAME}"
echo "ログ確認: sudo journalctl -u ${DAEMON_NAME} -f"
