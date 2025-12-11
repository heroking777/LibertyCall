"""
手動実行用バッチスクリプト
営業メール送信を手動で実行
"""

import sys
import argparse
from .scheduler_service_prod import send_batch

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="営業メール送信バッチを実行")
    parser.add_argument(
        "--simulation",
        "-s",
        action="store_true",
        help="シミュレーションモード（実際には送信しない）"
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="送信上限（デフォルト: シミュレーションモードは10件、本番モードは200件）"
    )
    
    args = parser.parse_args()
    
    send_batch(simulation=args.simulation, limit=args.limit)

