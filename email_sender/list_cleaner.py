"""
リストクリーニング機能
SendGrid APIからバウンス・スパムレポートを取得してリストを自動クリーンアップ
"""

import json
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
    
    def get_suppressed_emails(self, days_back: int = 7) -> Dict[str, Set[str]]:
        """
        SendGridからサプレッションリストを取得
        
        Args:
            days_back: 何日前まで遡るか
        
        Returns:
            各種サプレッションメールアドレスの辞書
        """
        if not self.sg:
            logger.error("SendGrid APIキーが設定されていません")
            return {"bounces": set(), "spam_reports": set(), "unsubscribes": set()}
        
        suppressed = {
            "bounces": set(),
            "spam_reports": set(), 
            "unsubscribes": set()
        }
        
        try:
            # バウンスリストを取得
            response = self.sg.client.suppression.bounces.get()
            if response.status_code == 200:
                bounces = json.loads(response.body)
                for bounce in bounces:
                    email = bounce.get("email", "")
                    created = bounce.get("created", "")
                    
                    # 日付フィルタリング
                    if self._is_within_days(created, days_back):
                        suppressed["bounces"].add(email)
                        logger.debug(f"バウンス検出: {email} ({created})")
            
            # スパムレポートを取得
            response = self.sg.client.suppression.spam_reports.get()
            if response.status_code == 200:
                spam_reports = json.loads(response.body)
                for spam in spam_reports:
                    email = spam.get("email", "")
                    created = spam.get("created", "")
                    
                    if self._is_within_days(created, days_back):
                        suppressed["spam_reports"].add(email)
                        logger.debug(f"スパムレポート検出: {email} ({created})")
            
            # 配信停止リストを取得
            response = self.sg.client.suppression.unsubscribes.get()
            if response.status_code == 200:
                unsubscribes = json.loads(response.body)
                for unsubscribe in unsubscribes:
                    email = unsubscribe.get("email", "")
                    created = unsubscribe.get("created", "")
                    
                    if self._is_within_days(created, days_back):
                        suppressed["unsubscribes"].add(email)
                        logger.debug(f"配信停止検出: {email} ({created})")
            
            logger.info(f"サプレッションリスト取得完了: "
                       f"バウンス={len(suppressed['bounces'])}, "
                       f"スパム={len(suppressed['spam_reports'])}, "
                       f"配信停止={len(suppressed['unsubscribes'])}")
            
        except Exception as e:
            logger.error(f"サプレッションリスト取得エラー: {e}")
        
        return suppressed
    
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
    
    def clean_recipient_list(self, recipients: List[Dict], 
                           suppressed: Dict[str, Set[str]]) -> List[Dict]:
        """
        レシピエントリストからサプレッションメールを除外
        
        Args:
            recipients: レシピエントリスト
            suppressed: サプレッションメールアドレスの辞書
        
        Returns:
        クリーンアップ後のレシピエントリスト
        """
        cleaned_recipients = []
        removed_count = 0
        
        # すべてのサプレッションメールを統合
        all_suppressed = set()
        all_suppressed.update(suppressed["bounces"])
        all_suppressed.update(suppressed["spam_reports"])
        all_suppressed.update(suppressed["unsubscribes"])
        
        for recipient in recipients:
            email = recipient.get("email", "").strip().lower()
            
            if email in all_suppressed:
                removed_count += 1
                
                # 除外理由をログ
                if email in suppressed["bounces"]:
                    reason = "バウンス"
                elif email in suppressed["spam_reports"]:
                    reason = "スパムレポート"
                elif email in suppressed["unsubscribes"]:
                    reason = "配信停止"
                else:
                    reason = "不明"
                
                logger.info(f"除外: {email} ({reason})")
                continue
            
            cleaned_recipients.append(recipient)
        
        self.cleaned_count = removed_count
        logger.info(f"リストクリーニング完了: {removed_count}件を除外、{len(cleaned_recipients)}件を残存")
        
        return cleaned_recipients
    
    def generate_cleaning_report(self, suppressed: Dict[str, Set[str]]) -> Dict:
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
            "bounces_count": len(suppressed["bounces"]),
            "spam_reports_count": len(suppressed["spam_reports"]),
            "unsubscribes_count": len(suppressed["unsubscribes"]),
            "total_suppressed": len(suppressed["bounces"]) + len(suppressed["spam_reports"]) + len(suppressed["unsubscribes"]),
            "bounced_emails": list(suppressed["bounces"]),
            "spam_reported_emails": list(suppressed["spam_reports"]),
            "unsubscribed_emails": list(suppressed["unsubscribes"])
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
        リストクリーニングを実行
        
        Args:
            days_back: 何日前まで遡るか
            save_report: レポートを保存するか
        
        Returns:
            クリーンアップした件数
        """
        logger.info(f"=== リストクリーニング開始（{days_back}日前まで） ===")
        
        # レシピエントリストを読み込み
        recipients = load_recipients()
        original_count = len(recipients)
        logger.info(f"元のリスト件数: {original_count}")
        
        # サプレッションリストを取得
        suppressed = self.get_suppressed_emails(days_back)
        
        # リストをクリーニング
        cleaned_recipients = self.clean_recipient_list(recipients, suppressed)
        
        # クリーンアップしたリストを保存
        save_recipients(cleaned_recipients)
        
        # レポートを生成・保存
        if save_report:
            report = self.generate_cleaning_report(suppressed)
            self.save_cleaning_report(report)
        
        logger.info(f"=== リストクリーニング完了 ===")
        logger.info(f"結果: {original_count} → {len(cleaned_recipients)} (除外: {self.cleaned_count})")
        
        return self.cleaned_count


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
