#!/usr/bin/env python3
"""
日次送信レポート生成スクリプト
毎日23:55に実行され、当日の送信状況をレポートして通知メールを送信する
"""

import sys
import json
import csv
import logging
from datetime import datetime, date
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from email_sender.sendgrid_client import send_notification_email
from email_sender.csv_repository_prod import load_recipients

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_daily_limit():
    """daily_limit.jsonを読み込む"""
    try:
        limit_file = Path(__file__).parent / "daily_limit.json"
        with open(limit_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"daily_limit.json読み込みエラー: {e}")
        return {"daily_limit": 50, "date": str(date.today())}

def count_today_sent():
    """今日送信された件数をログからカウント"""
    today = date.today().strftime('%Y-%m-%d')
    log_file = Path("/var/log/continuous_sender.log")
    
    success_count = 0
    fail_count = 0
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if today in line:
                    if "送信成功" in line:
                        success_count += 1
                    elif "失敗" in line or "エラー" in line or "バウンス" in line or "error" in line:
                        fail_count += 1
    except Exception as e:
        logger.error(f"ログ読み込みエラー: {e}")
    
    return success_count, fail_count

def analyze_stages():
    """stageごとの件数を集計"""
    try:
        recipients = load_recipients()
        stage_counts = {}
        
        for recipient in recipients:
            stage = recipient.get('stage', 'unknown')
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        
        return stage_counts
    except Exception as e:
        logger.error(f"stage分析エラー: {e}")
        return {}

def count_unsent():
    """未送信件数をカウント"""
    try:
        recipients = load_recipients()
        unsent = sum(1 for r in recipients if not r.get('last_sent_date'))
        return unsent
    except Exception as e:
        logger.error(f"未送信カウントエラー: {e}")
        return 0

def main():
    """メイン処理"""
    try:
        today = date.today()
        logger.info(f"=== 日次レポート生成開始: {today} ===")
        
        # 各種データ収集
        daily_limit = load_daily_limit()
        success_count, fail_count = count_today_sent()
        stage_counts = analyze_stages()
        unsent_count = count_unsent()
        
        # バウンス率計算
        total_sent = success_count + fail_count
        bounce_rate = (fail_count / total_sent * 100) if total_sent > 0 else 0
        
        # レポート本文作成
        report_lines = [
            "LibertyCall 日次送信レポート",
            "",
            f"日付: {today.strftime('%Y年%m月%d日')}",
            "",
            "=== 送信結果 ===",
            f"送信成功: {success_count}件",
            f"送信失敗: {fail_count}件",
            f"バウンス率: {bounce_rate:.1f}%",
            f"送信上限: {daily_limit.get('daily_limit', 'N/A')}件",
            "",
            "=== Stage別件数 ===",
        ]
        
        for stage, count in sorted(stage_counts.items()):
            report_lines.append(f"{stage}: {count}件")
        
        report_lines.extend([
            "",
            "=== その他 ===",
            f"未送信件数: {unsent_count}件",
            f"総レコード数: {sum(stage_counts.values())}件",
            "",
            "---",
            f"レポート生成時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ])
        
        report_body = "\n".join(report_lines)
        
        # レポートをログに出力
        logger.info("日次レポート内容:")
        logger.info("\n" + report_body)
        
        # 通知メール送信
        success = send_notification_email(
            sent_count=success_count,
            failed_count=fail_count,
            error_message=None
        )
        
        if success:
            logger.info("日次レポートメールを送信しました")
        else:
            logger.error("日次レポートメールの送信に失敗しました")
        
        logger.info("=== 日次レポート生成完了 ===")
        
    except Exception as e:
        logger.error(f"日次レポート生成エラー: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
