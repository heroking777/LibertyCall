#!/bin/bash
# LibertyCall ローンチ用スナップショット作成スクリプト

set -e

# 日付を取得
DATE=$(date +%F)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# バックアップディレクトリ
BACKUP_DIR="/var/backups/libertycall"
SNAPSHOT_NAME="libertycall_000_${DATE}.tar.gz"

# バックアップディレクトリを作成
mkdir -p "$BACKUP_DIR"

echo "📦 LibertyCall ローンチ用スナップショットを作成中..."

# バックアップ対象
BACKUP_PATHS=(
    "/opt/libertycall"
    "/usr/local/freeswitch/conf"
)

# tar.gzでアーカイブ
tar czf "${BACKUP_DIR}/${SNAPSHOT_NAME}" "${BACKUP_PATHS[@]}" 2>/dev/null || {
    echo "❌ エラー: バックアップの作成に失敗しました"
    exit 1
}

echo "✅ スナップショットを作成しました: ${BACKUP_DIR}/${SNAPSHOT_NAME}"

# Gitタグの作成（オプション）
if [ -d "/opt/libertycall/.git" ]; then
    cd /opt/libertycall
    if git rev-parse --git-dir > /dev/null 2>&1; then
        TAG_NAME="v1.0-launch-000-${TIMESTAMP}"
        echo "🏷️  Gitタグを作成中: ${TAG_NAME}"
        git tag -a "${TAG_NAME}" -m "LibertyCall Client000 launch build - ${DATE}" || {
            echo "⚠️  警告: Gitタグの作成に失敗しました（既に存在する可能性があります）"
        }
        echo "✅ Gitタグを作成しました: ${TAG_NAME}"
        echo "   プッシュする場合: git push origin ${TAG_NAME}"
    fi
fi

echo ""
echo "📋 スナップショット情報:"
echo "   ファイル: ${BACKUP_DIR}/${SNAPSHOT_NAME}"
echo "   サイズ: $(du -h "${BACKUP_DIR}/${SNAPSHOT_NAME}" | cut -f1)"
echo ""
echo "✅ ローンチ用スナップショットの作成が完了しました"

