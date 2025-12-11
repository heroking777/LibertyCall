"""
スケジューラー
「今日送るべきメール」を判断するロジック
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from .models import Recipient
from .config import Config


class Scheduler:
    """送信スケジュールを管理するクラス"""
    
    def __init__(self):
        self.config = Config
    
    def should_send_initial(self, recipient: Recipient) -> bool:
        """初回メールを送信すべきか判定"""
        return recipient.stage == "initial" and not recipient.initial_sent_at
    
    def should_send_followup1(self, recipient: Recipient) -> bool:
        """フォローアップ1を送信すべきか判定"""
        if recipient.stage != "followup1" or not recipient.initial_sent_at:
            return False
        
        initial_dt = datetime.fromisoformat(recipient.initial_sent_at)
        days_passed = (datetime.now().date() - initial_dt.date()).days
        
        return days_passed >= self.config.FOLLOWUP1_DAYS_AFTER
    
    def should_send_followup2(self, recipient: Recipient) -> bool:
        """フォローアップ2を送信すべきか判定"""
        if recipient.stage != "followup2" or not recipient.followup1_sent_at:
            return False
        
        followup1_dt = datetime.fromisoformat(recipient.followup1_sent_at)
        days_passed = (datetime.now().date() - followup1_dt.date()).days
        
        return days_passed >= self.config.FOLLOWUP2_DAYS_AFTER
    
    def should_send_followup3(self, recipient: Recipient) -> bool:
        """フォローアップ3を送信すべきか判定"""
        if recipient.stage != "followup3" or not recipient.followup2_sent_at:
            return False
        
        followup2_dt = datetime.fromisoformat(recipient.followup2_sent_at)
        days_passed = (datetime.now().date() - followup2_dt.date()).days
        
        return days_passed >= self.config.FOLLOWUP3_DAYS_AFTER
    
    def get_next_stage(self, recipient: Recipient) -> Optional[str]:
        """
        次に送信すべきステージを取得
        
        Returns:
            送信すべきステージ名（"initial", "followup1", "followup2", "followup3"）
            送信不要な場合はNone
        """
        if self.should_send_initial(recipient):
            return "initial"
        elif self.should_send_followup1(recipient):
            return "followup1"
        elif self.should_send_followup2(recipient):
            return "followup2"
        elif self.should_send_followup3(recipient):
            return "followup3"
        
        return None
    
    def get_recipients_to_send(
        self, recipients: List[Recipient], limit: Optional[int] = None
    ) -> List[Tuple[Recipient, str]]:
        """
        今日送信すべきレシピエントとステージのリストを取得
        
        Args:
            recipients: 全レシピエントのリスト
            limit: 最大送信数（Noneの場合は制限なし）
        
        Returns:
            (Recipient, stage)のタプルのリスト
        """
        to_send = []
        
        for recipient in recipients:
            stage = self.get_next_stage(recipient)
            if stage:
                to_send.append((recipient, stage))
        
        # 制限がある場合は先頭から取得
        if limit and len(to_send) > limit:
            to_send = to_send[:limit]
        
        return to_send
