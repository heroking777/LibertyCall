"""
CSVリポジトリ
recipients.csvの読み込み・書き込みを行う
配信停止リストのチェック機能も含む
"""

import csv
import os
from typing import List, Optional, Set
from .models import Recipient
from .config import Config


class CSVRepository:
    """CSVファイルの読み書きを行うリポジトリクラス"""
    
    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = csv_path or Config.RECIPIENTS_CSV_PATH
        self.unsubscribe_list_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "unsubscribe_list.csv"
        )
    
    def read_all(self) -> List[Recipient]:
        """CSVファイルから全レコードを読み込む"""
        if not os.path.exists(self.csv_path):
            return []
        
        recipients = []
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 空の値をNoneに変換
                cleaned_row = {
                    k: (v if v.strip() else None) for k, v in row.items()
                }
                recipients.append(Recipient.from_dict(cleaned_row))
        
        return recipients
    
    def write_all(self, recipients: List[Recipient]):
        """全レコードをCSVファイルに書き込む"""
        if not recipients:
            return
        
        # ディレクトリが存在しない場合は作成
        os.makedirs(os.path.dirname(self.csv_path) or ".", exist_ok=True)
        
        fieldnames = [
            "id",
            "email",
            "name",
            "stage",
            "initial_sent_at",
            "followup1_sent_at",
            "followup2_sent_at",
            "followup3_sent_at",
            "last_sent_at",
        ]
        
        with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for recipient in recipients:
                writer.writerow(recipient.to_dict())
    
    def find_by_id(self, id: str) -> Optional[Recipient]:
        """IDでレコードを検索"""
        recipients = self.read_all()
        for recipient in recipients:
            if recipient.id == id:
                return recipient
        return None
    
    def save(self, recipient: Recipient):
        """1件のレコードを保存（更新または追加）"""
        recipients = self.read_all()
        
        # 既存レコードを更新
        found = False
        for i, r in enumerate(recipients):
            if r.id == recipient.id:
                recipients[i] = recipient
                found = True
                break
        
        # 新規レコードを追加
        if not found:
            recipients.append(recipient)
        
        self.write_all(recipients)
    
    def get_unsubscribed_emails(self) -> Set[str]:
        """配信停止リストからメールアドレスのセットを取得"""
        unsubscribed = set()
        
        if not os.path.exists(self.unsubscribe_list_path):
            return unsubscribed
        
        try:
            with open(self.unsubscribe_list_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # ヘッダーをスキップ
                for row in reader:
                    if row and row[0]:
                        unsubscribed.add(row[0].lower().strip())
        except Exception as e:
            print(f"配信停止リストの読み込みエラー: {e}")
        
        return unsubscribed
    
    def is_unsubscribed(self, email: str) -> bool:
        """メールアドレスが配信停止リストに含まれているか確認"""
        email_lower = email.lower().strip()
        unsubscribed = self.get_unsubscribed_emails()
        return email_lower in unsubscribed
    
    def filter_unsubscribed(self, recipients: List[Recipient]) -> List[Recipient]:
        """配信停止済みのレシピエントを除外"""
        unsubscribed = self.get_unsubscribed_emails()
        return [
            r for r in recipients
            if r.email.lower().strip() not in unsubscribed
        ]

