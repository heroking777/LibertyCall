"""
本番用CSVリポジトリ
営業メール送信用のCSV操作
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set

# SendGridイベントログから除外する無効イベント
INVALID_EVENTS = {"bounce", "dropped", "spamreport", "auto_reply"}


def load_invalid_emails_from_sendgrid() -> Set[str]:
    """
    SendGridイベントログから無効メールを取得
    
    Returns:
        無効メールアドレスのセット
    """
    invalid_emails = set()
    
    # ログファイルのパス（プロジェクトルートのlogsディレクトリ）
    project_root = Path(__file__).parent.parent.parent
    log_path = project_root / "logs" / "sendgrid_events.csv"
    
    if not log_path.exists():
        return invalid_emails
    
    try:
        with open(log_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # ヘッダーをスキップ
            for row in reader:
                if len(row) >= 2:
                    email = row[0].strip().lower()
                    event = row[1].strip().lower()
                    if event in INVALID_EVENTS:
                        invalid_emails.add(email)
    except Exception as e:
        print(f"[WARN] Failed to load invalid emails from SendGrid log: {e}")
    
    return invalid_emails


class ProductionCSVRepository:
    """本番用CSVリポジトリクラス"""
    
    def __init__(self, recipients_file: str = None, unsubscribe_file: str = None):
        """
        初期化
        
        Args:
            recipients_file: 送信先CSVファイルのパス
            unsubscribe_file: 配信停止リストCSVファイルのパス
        """
        if recipients_file:
            self.recipients_file = Path(recipients_file)
        else:
            # デフォルトパス: master_leads.csvを直接使用
            self.recipients_file = Path(__file__).parent.parent / "corp_collector" / "data" / "output" / "master_leads.csv"
        
        if unsubscribe_file:
            self.unsubscribe_file = Path(unsubscribe_file)
        else:
            # デフォルトパス
            self.unsubscribe_file = Path(__file__).parent.parent / "unsubscribe_list.csv"
    
    def load_unsubscribed(self) -> Set[str]:
        """配信停止リストからメールアドレスのセットを取得"""
        unsubscribed = set()
        
        if not self.unsubscribe_file.exists():
            return unsubscribed
        
        try:
            with open(self.unsubscribe_file, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                next(reader, None)  # ヘッダーをスキップ
                for row in reader:
                    if row and row[0]:
                        unsubscribed.add(row[0].strip().lower())
        except Exception as e:
            print(f"配信停止リストの読み込みエラー: {e}")
        
        return unsubscribed
    
    def load_recipients(self) -> List[Dict]:
        """
        送信先リストを読み込む（配信停止済み・無効メールを除外）
        master_leads.csvの形式に対応
        
        Returns:
            送信先の辞書リスト
        """
        recipients = []
        unsubscribed = self.load_unsubscribed()
        invalid_emails = load_invalid_emails_from_sendgrid()
        
        if not self.recipients_file.exists():
            return recipients
        
        try:
            with open(self.recipients_file, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = row.get("email", "").strip()
                    if not email:
                        continue
                    
                    # 配信停止済みを除外
                    if email.lower() in unsubscribed:
                        continue
                    
                    # SendGridイベントログから無効メールを除外
                    if email.lower() in invalid_emails:
                        print(f"[SKIP] Invalid email skipped (SendGrid event): {email}")
                        continue
                    
                    # master_leads.csvの形式をrecipients.csvの形式に変換
                    # master_leads.csv: email,company_name,address,stage
                    # recipients.csv: company_name,contact_name,email,phone,industry,prefecture,stage,last_sent_date
                    stage_value = row.get("stage", "").strip() if row.get("stage") else "initial"
                    if not stage_value:
                        stage_value = "initial"
                    
                    recipient = {
                        "company_name": row.get("company_name", "").strip(),
                        "contact_name": "担当者様",  # デフォルト値
                        "email": email,
                        "phone": "",  # master_leads.csvには電話番号がない
                        "industry": "",  # master_leads.csvには業種がない
                        "prefecture": "",  # master_leads.csvには都道府県がない
                        "stage": stage_value,
                        "last_sent_date": row.get("last_sent_date", "").strip() if row.get("last_sent_date") else "",
                        "initial_sent_date": row.get("initial_sent_date", "").strip() if row.get("initial_sent_date") else ""
                    }
                    
                    recipients.append(recipient)
        except Exception as e:
            print(f"送信先リストの読み込みエラー: {e}")
        
        print(f"Loaded {len(recipients)} valid recipients (excluded {len(unsubscribed)} unsubscribed, {len(invalid_emails)} invalid from SendGrid events)")
        return recipients
    
    def save_recipients(self, recipients: List[Dict]):
        """
        送信先リストを保存
        master_leads.csvの形式で保存
        全件を読み込んで、更新されたレコードだけを更新して保存
        
        Args:
            recipients: 更新された送信先の辞書リスト（全件または更新されたレコードのみ）
        """
        if not recipients:
            return
        
        # ディレクトリが存在しない場合は作成
        self.recipients_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 全件を読み込む
        all_recipients = self.load_recipients()
        
        # 更新されたレコードのメールアドレスを取得
        updated_emails = {r.get("email", "").lower() for r in recipients if r.get("email")}
        
        # 更新されたレコードで既存のレコードを上書き
        recipients_dict = {r.get("email", "").lower(): r for r in all_recipients}
        for updated in recipients:
            email = updated.get("email", "").lower()
            if email:
                recipients_dict[email] = updated
        
        # 全件をmaster_leads.csvの形式で保存
        try:
            # 既存のmaster_leads.csvを読み込んで、address、last_sent_date、initial_sent_dateフィールドを保持
            existing_data = {}
            if self.recipients_file.exists():
                with open(self.recipients_file, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        email = row.get("email", "").strip().lower()
                        if email:
                            existing_data[email] = {
                                "address": row.get("address", "").strip(),
                                "last_sent_date": row.get("last_sent_date", "").strip(),
                                "initial_sent_date": row.get("initial_sent_date", "").strip()
                            }
            
            with open(self.recipients_file, "w", encoding="utf-8", newline="") as f:
                fieldnames = ["email", "company_name", "address", "stage", "last_sent_date", "initial_sent_date"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for recipient in recipients_dict.values():
                    email_lower = recipient.get("email", "").strip().lower()
                    existing = existing_data.get(email_lower, {})
                    # recipients.csvの形式からmaster_leads.csvの形式に変換
                    row = {
                        "email": recipient.get("email", ""),
                        "company_name": recipient.get("company_name", ""),
                        "address": recipient.get("address", "") or existing.get("address", ""),  # 既存のaddressを保持
                        "stage": recipient.get("stage", "initial"),
                        "last_sent_date": recipient.get("last_sent_date", "") or existing.get("last_sent_date", ""),  # 既存のlast_sent_dateを保持
                        "initial_sent_date": recipient.get("initial_sent_date", "") or existing.get("initial_sent_date", "")  # 既存のinitial_sent_dateを保持
                    }
                    writer.writerow(row)
        except Exception as e:
            print(f"送信先リストの保存エラー: {e}")
            raise
    
    def remove_emails(self, emails_to_remove: List[str]):
        """
        指定されたメールアドレスをリストから削除
        
        Args:
            emails_to_remove: 削除するメールアドレスのリスト
        """
        if not emails_to_remove:
            return
        
        emails_to_remove_lower = {email.lower() for email in emails_to_remove if email}
        
        # 既存のCSVを読み込む
        existing_records = []
        if self.recipients_file.exists():
            with open(self.recipients_file, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    email = row.get("email", "").strip().lower()
                    if email and email not in emails_to_remove_lower:
                        existing_records.append(row)
        
        # 削除後のレコードを保存
        if fieldnames:
            with open(self.recipients_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(existing_records)
        
        print(f"削除したメールアドレス数: {len(emails_to_remove_lower)}")


# グローバル関数（後方互換性のため）
def load_recipients(recipients_file: str = None) -> List[Dict]:
    """送信先リストを読み込む"""
    repo = ProductionCSVRepository(recipients_file=recipients_file)
    return repo.load_recipients()


def save_recipients(recipients: List[Dict], recipients_file: str = None):
    """送信先リストを保存"""
    repo = ProductionCSVRepository(recipients_file=recipients_file)
    repo.save_recipients(recipients)

