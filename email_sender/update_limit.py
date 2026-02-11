#!/usr/bin/env python3
"""
送信上限自動更新スクリプト
毎日23:58に実行され、SendGridのバウンス率に基づいて翌日の送信上限を更新する
"""

import sys
import logging
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from email_sender.sendgrid_analytics import update_daily_limit_automatically

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """メイン処理"""
    try:
        logger.info("=== 送信上限自動更新開始 ===")
        
        # 送信上限を自動更新
        new_limit = update_daily_limit_automatically()
        
        logger.info(f"送信上限を更新しました: {new_limit}件")
        logger.info("=== 送信上限自動更新完了 ===")
        
    except Exception as e:
        logger.error(f"送信上限更新エラー: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
