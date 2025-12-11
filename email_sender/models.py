"""
データモデル
CSVの1行を表すRecipientクラス
"""

from datetime import datetime
from typing import Optional


class Recipient:
    """メール送信先を表すモデル"""
    
    def __init__(
        self,
        id: str,
        email: str,
        name: str,
        stage: str = "initial",
        initial_sent_at: Optional[str] = None,
        followup1_sent_at: Optional[str] = None,
        followup2_sent_at: Optional[str] = None,
        followup3_sent_at: Optional[str] = None,
        last_sent_at: Optional[str] = None,
    ):
        self.id = id
        self.email = email
        self.name = name
        self.stage = stage  # initial, followup1, followup2, followup3, completed
        self.initial_sent_at = initial_sent_at
        self.followup1_sent_at = followup1_sent_at
        self.followup2_sent_at = followup2_sent_at
        self.followup3_sent_at = followup3_sent_at
        self.last_sent_at = last_sent_at
    
    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "stage": self.stage,
            "initial_sent_at": self.initial_sent_at or "",
            "followup1_sent_at": self.followup1_sent_at or "",
            "followup2_sent_at": self.followup2_sent_at or "",
            "followup3_sent_at": self.followup3_sent_at or "",
            "last_sent_at": self.last_sent_at or "",
        }
    
    @classmethod
    def from_dict(cls, row: dict) -> "Recipient":
        """辞書からRecipientオブジェクトを作成"""
        return cls(
            id=row.get("id", ""),
            email=row.get("email", ""),
            name=row.get("name", ""),
            stage=row.get("stage", "initial"),
            initial_sent_at=row.get("initial_sent_at") or None,
            followup1_sent_at=row.get("followup1_sent_at") or None,
            followup2_sent_at=row.get("followup2_sent_at") or None,
            followup3_sent_at=row.get("followup3_sent_at") or None,
            last_sent_at=row.get("last_sent_at") or None,
        )
    
    def update_sent_at(self, stage: str):
        """送信日時を更新"""
        now = datetime.now().isoformat()
        self.last_sent_at = now
        
        if stage == "initial":
            self.initial_sent_at = now
            self.stage = "followup1"
        elif stage == "followup1":
            self.followup1_sent_at = now
            self.stage = "followup2"
        elif stage == "followup2":
            self.followup2_sent_at = now
            self.stage = "followup3"
        elif stage == "followup3":
            self.followup3_sent_at = now
            self.stage = "completed"

