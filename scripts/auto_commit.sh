#!/bin/bash
cd /opt/libertycall || exit 1
CHANGES=$(git status --porcelain)
if [ -n "$CHANGES" ]; then
    echo "🔄 変更を検出。コミット＆プッシュを実行します..."
    git pull origin main --rebase
    git add .
    git commit -m "🤖 Auto commit by AI $(date '+%Y-%m-%d %H:%M:%S')" || true
    git push origin main
    echo "✅ 自動プッシュ完了 $(date)"
else
    echo "✨ 変更なし。スキップ。$(date)"
fi
