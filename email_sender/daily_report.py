#!/usr/bin/env python3
"""
日次送信レポート生成スクリプト
毎日23:55に実行され、当日の送信状況をレポートして通知メールを送信する
"""

import sys
import json
import csv
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Optional

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from email_sender.sendgrid_client import send_notification_email
from email_sender.csv_repository_prod import load_recipients
from email_sender.sendgrid_analytics import get_today_stats

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

def get_sendgrid_stats() -> Optional[Dict]:
    """SendGrid APIから今日の統計を取得"""
    try:
        stats_dict, bounce_rate, spam_rate = get_today_stats()
        
        # 追加の統計を取得（opens, clicks, blocks, unsubscribes）
        from sendgrid import SendGridAPIClient
        from email_sender.sendgrid_client import SENDGRID_API_KEY
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        
        # 今日の日付範囲
        today = datetime.now().date().strftime("%Y-%m-%d")
        start_date = today
        
        # 詳細統計取得
        detailed_stats = {
            "opens": 0,
            "clicks": 0,
            "blocks": 0,
            "unsubscribes": 0
        }
        
        try:
            # Global statsから詳細情報を取得
            query_params = {
                "start_date": start_date,
                "end_date": start_date,
                "aggregated_by": "day",
                "metrics": "opens,clicks,blocks,unsubscribes"
            }
            response = sg.client.stats.get(query_params=query_params)
            
            if response.status_code == 200:
                data = json.loads(response.body)
                if data and len(data) > 0:
                    metrics = data[0]["stats"][0]["metrics"]
                    detailed_stats["opens"] = metrics.get("opens", 0)
                    detailed_stats["clicks"] = metrics.get("clicks", 0)
                    detailed_stats["blocks"] = metrics.get("blocks", 0)
                    detailed_stats["unsubscribes"] = metrics.get("unsubscribes", 0)
        except Exception as e:
            logger.warning(f"詳細統計取得エラー: {e}")
        
        # 統計をマージ
        combined_stats = {**stats_dict, **detailed_stats}
        
        # 開封率を計算
        delivered = combined_stats.get("delivered", 0)
        opens = combined_stats.get("opens", 0)
        open_rate = (opens / delivered * 100) if delivered > 0 else 0
        combined_stats["open_rate"] = open_rate
        
        return combined_stats
        
    except Exception as e:
        logger.error(f"SendGrid統計取得エラー: {e}")
        return None

def count_list_status():
    """リスト状況を集計"""
    try:
        master_path = Path("/opt/libertycall/email_sender/data/master_leads.csv")
        total = flagged = sent = unsent = 0
        
        with open(master_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += 1
                if row.get("除外", "").strip():
                    flagged += 1
                elif row.get("last_sent_date", "").strip():
                    sent += 1
                else:
                    unsent += 1
        
        return {
            "total": total,
            "flagged": flagged,
            "active": total - flagged,
            "sent": sent,
            "unsent": unsent
        }
    except Exception as e:
        logger.error(f"リスト状況集計エラー: {e}")
        return {"total": 0, "flagged": 0, "active": 0, "sent": 0, "unsent": 0}

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
        list_status = count_list_status()
        stage_counts = analyze_stages()
        sendgrid_stats = get_sendgrid_stats()
        
        # レポート本文作成
        report_lines = [
            "LibertyCall メール送信システム",
            f"送信日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
            "",
            "=== 送信結果（ログベース）===",
            f"送信件数: {list_status['sent']}件",
            f"成功: {list_status['sent']}件",
            f"失敗: 0件"
        ]
        
        if sendgrid_stats:
            delivered = sendgrid_stats.get("delivered", 0)
            opens = sendgrid_stats.get("opens", 0)
            open_rate = sendgrid_stats.get("open_rate", 0)
            
            report_lines.extend([
                "",
                "=== SendGrid 実績（API）===",
                f"リクエスト: {sendgrid_stats.get('requests', 0)}件",
                f"配信成功: {delivered}件",
                f"バウンス: {sendgrid_stats.get('bounces', 0)}件",
                f"ブロック: {sendgrid_stats.get('blocks', 0)}件",
                f"開封: {opens}件（開封率: {open_rate:.1f}%）",
                f"クリック: {sendgrid_stats.get('clicks', 0)}件",
                f"スパム報告: {sendgrid_stats.get('spam_reports', 0)}件",
                f"配信停止: {sendgrid_stats.get('unsubscribes', 0)}件"
            ])
        else:
            report_lines.extend([
                "",
                "=== SendGrid 実績（API）===",
                "統計取得失敗"
            ])
        
        report_lines.extend([
            "",
            "=== リスト状況 ===",
            f"総リスト数: {list_status['total']}件",
            f"除外フラグ: {list_status['flagged']}件",
            f"送信対象: {list_status['active']}件",
            f"送信済み: {list_status['sent']}件（stage別内訳）",
            f"未送信: {list_status['unsent']}件",
            "",
            "=== 送信上限 ===",
            f"本日の上限: {daily_limit.get('daily_limit', 'N/A')}件",
            f"明日の上限: {daily_limit.get('daily_limit', 'N/A')}件（予定）"
        ])
        
        # Stage別内訳を追加
        if stage_counts:
            report_lines.append("")
            report_lines.append("=== Stage別内訳 ===")
            for stage, count in sorted(stage_counts.items()):
                report_lines.append(f"{stage}: {count}件")
        
        report_lines.extend([
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
            sent_count=list_status['sent'],
            failed_count=0,
            error_message=None,
            custom_body=report_body
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
