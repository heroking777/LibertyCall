"""
リストクリーニング機能
SendGrid APIからバウンス・スパムレポートを取得してリストを自動クリーンアップ
"""

import json
import csv
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Set

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from email_sender.scheduler_service_prod import load_recipients, save_recipients
from email_sender.sendgrid_client import SENDGRID_API_KEY
from sendgrid import SendGridAPIClient


class ListCleaner:
    """リストクリーナー"""
    
    def __init__(self):
        self.sg = SendGridAPIClient(SENDGRID_API_KEY) if SENDGRID_API_KEY else None
        self.cleaned_count = 0
        self.bounced_emails = set()
        self.spam_reported_emails = set()
        self.unsubscribed_emails = set()
    
    def get_suppressed_emails(self, days_back: int = None) -> Set[str]:
        """
        SendGridからサプレッションリストを取得（全期間）
        
        Args:
            days_back: 無視（全期間取得）
        
        Returns:
            サプレッションメールアドレスのセット
        """
        if not self.sg:
            logger.error("SendGrid APIキーが設定されていません")
            return set()
        
        suppress_emails = set()
        
        # バウンス
        try:
            response = self.sg.client.suppression.bounces.get()
            bounces = json.loads(response.body)
            for b in bounces:
                suppress_emails.add(b["email"])
            print(f"バウンス: {len(bounces)}件")
        except Exception as e:
            print(f"バウンス取得エラー: {e}")
        
        # ブロック
        try:
            response = self.sg.client.suppression.blocks.get()
            blocks = json.loads(response.body)
            for b in blocks:
                suppress_emails.add(b["email"])
            print(f"ブロック: {len(blocks)}件")
        except Exception as e:
            print(f"ブロック取得エラー: {e}")
        
        # スパム報告
        try:
            response = self.sg.client.suppression.spam_reports.get()
            spams = json.loads(response.body)
            for s in spams:
                suppress_emails.add(s["email"])
            print(f"スパム報告: {len(spams)}件")
        except Exception as e:
            print(f"スパム報告取得エラー: {e}")
        
        return suppress_emails
    
    def _is_within_days(self, date_input, days: int) -> bool:
        """
        日付が指定日数以内かチェック
        
        Args:
            date_input: 日付（文字列または数値）
            days: 日数
        
        Returns:
            指定日数以内ならTrue
        """
        if not date_input:
            return False
        
        try:
            # 数値（Unixタイムスタンプ）の場合
            if isinstance(date_input, (int, float)):
                date_obj = datetime.fromtimestamp(date_input)
            else:
                date_str = str(date_input)
                
                # SendGridの日付形式: "Thu, 01 Jan 2023 12:00:00 GMT"
                try:
                    date_obj = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
                except ValueError:
                    # ISO形式も試す
                    try:
                        date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    except ValueError:
                        # Unixタイムスタンプ文字列も試す
                        try:
                            timestamp = int(date_str)
                            date_obj = datetime.fromtimestamp(timestamp)
                        except ValueError:
                            logger.warning(f"無効な日付形式: {date_input}")
                            return False
            
            cutoff_date = datetime.now() - timedelta(days=days)
            return date_obj >= cutoff_date
            
        except Exception as e:
            logger.warning(f"日付解析エラー: {date_input}, エラー: {e}")
            return False
    
    def flag_suppressed_emails_in_master(self, suppressed_emails: Set[str]) -> int:
        """
        master_leads.csvのサプレッション対象メールに除外フラグを立てる
        
        Args:
            suppressed_emails: サプレッションメールアドレスのセット
        
        Returns:
            フラグを立てた件数
        """
        master_path = Path("/opt/libertycall/email_sender/data/master_leads.csv")
        
        if not master_path.exists():
            logger.error(f"master_leads.csvが見つかりません: {master_path}")
            return 0
        
        try:
            # CSV読み込み
            rows = []
            with open(master_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                
                # 除外列がなければ追加
                if "除外" not in fieldnames:
                    fieldnames = list(fieldnames) + ["除外"]
                
                for row in reader:
                    email = row.get("email", "").strip()
                    
                    # サプレッション対象なら除外フラグを立てる
                    if email.lower() in [e.lower() for e in suppressed_emails]:
                        if not row.get("除外", "").strip():  # 既にフラグがなければ
                            row["除外"] = "サプレッション"
                            self.cleaned_count += 1
                            logger.info(f"除外フラグ: {email}")
                    
                    rows.append(row)
            
            # CSV書き戻し
            with open(master_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            logger.info(f"除外フラグ設定完了: {self.cleaned_count}件")
            return self.cleaned_count
            
        except Exception as e:
            logger.error(f"除外フラグ設定エラー: {e}")
            return 0
    
    def generate_cleaning_report(self, suppressed: Set[str]) -> Dict:
        """
        クリーニングレポートを生成
        
        Args:
            suppressed: サプレッションメールアドレスの辞書
        
        Returns:
            レポート辞書
        """
        report = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "cleaned_count": self.cleaned_count,
            "total_suppressed": len(suppressed),
            "suppressed_emails": list(suppressed)
        }
        
        return report
    
    def save_cleaning_report(self, report: Dict) -> None:
        """
        クリーニングレポートを保存
        
        Args:
            report: レポート辞書
        """
        project_root = Path(__file__).parent.parent
        report_dir = project_root / "logs"
        report_dir.mkdir(exist_ok=True)
        
        report_file = report_dir / "list_cleaning_report.json"
        
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            logger.info(f"クリーニングレポートを保存: {report_file}")
            
        except Exception as e:
            logger.error(f"レポート保存エラー: {e}")
    
    def run_cleaning(self, days_back: int = 7, save_report: bool = True) -> int:
        """
        リストクリーニングを実行（除外フラグ方式）
        
        Args:
            days_back: 何日前まで遡るか（全期間取得のため無視）
            save_report: レポートを保存するか
        
        Returns:
            フラグを立てた件数
        """
        logger.info(f"=== リストクリーニング開始（除外フラグ方式） ===")
        
        # サプレッションリストを取得
        suppressed = self.get_suppressed_emails()
        logger.info(f"サプレッション対象: {len(suppressed)}件")
        
        # master_leads.csvに除外フラグを立てる
        flagged_count = self.flag_suppressed_emails_in_master(suppressed)
        
        # レポートを生成・保存
        if save_report:
            report = self.generate_cleaning_report(suppressed)
            self.save_cleaning_report(report)
        
        logger.info(f"=== リストクリーニング完了 ===")
        logger.info(f"結果: {flagged_count}件に除外フラグを設定")
        
        return flagged_count


def run_daily_cleaning() -> None:
    """毎日のクリーニングを実行"""
    cleaner = ListCleaner()
    cleaned_count = cleaner.run_cleaning(days_back=7)
    
    if cleaned_count > 0:
        logger.info(f"{cleaned_count}件のメールアドレスをクリーンアップしました")
    else:
        logger.info("クリーンアップ対象はありませんでした")


if __name__ == "__main__":
    import sys
    
    # コマンドライン引数で遡る日数を指定
    days_back = 7
    if len(sys.argv) > 1:
        try:
            days_back = int(sys.argv[1])
        except ValueError:
            logger.warning(f"無効な引数: {sys.argv[1]}、デフォルト値を使用")
    
    cleaner = ListCleaner()
    cleaner.run_cleaning(days_back=days_back)
