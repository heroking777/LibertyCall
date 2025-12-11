"""
ステージ管理モジュール
メール送信のステージを管理する機能を提供
"""

import csv
import logging
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger("corp_collector.stage_manager")

# ステージ定義
STAGES = {
    "initial": "初回メール送信前",
    "follow1": "フォローメール1送信済み",
    "follow2": "フォローメール2送信済み",
    "follow3": "フォローメール3送信済み",
    "completed": "すべてのフォローメール送信完了",
}

# 次のステージへのマッピング
NEXT_STAGE = {
    "initial": "follow1",
    "follow1": "follow2",
    "follow2": "follow3",
    "follow3": "completed",
    "completed": None,  # 完了後は次のステージなし
}


class StageManager:
    """ステージ管理クラス"""

    def __init__(self, master_file: Path):
        """
        初期化
        
        Args:
            master_file: マスターファイルのパス
        """
        self.master_file = Path(master_file)
        if not self.master_file.exists():
            raise FileNotFoundError(f"マスターファイルが見つかりません: {master_file}")

    def update_stage(self, email: str, new_stage: str) -> bool:
        """
        指定されたメールアドレスのステージを更新
        
        Args:
            email: メールアドレス
            new_stage: 新しいステージ（initial, follow1, follow2, follow3, completed）
        
        Returns:
            更新成功時True、失敗時False
        """
        if new_stage not in STAGES:
            logger.error(f"無効なステージ: {new_stage}")
            return False

        try:
            # CSVを読み込み
            rows = []
            updated = False
            with open(self.master_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                if "stage" not in fieldnames:
                    logger.error("CSVファイルにstage列がありません")
                    return False

                for row in reader:
                    if row.get("email", "").strip().lower() == email.lower():
                        row["stage"] = new_stage
                        updated = True
                        logger.info(f"ステージ更新: {email} -> {new_stage}")
                    rows.append(row)

            if not updated:
                logger.warning(f"メールアドレスが見つかりませんでした: {email}")
                return False

            # CSVに書き戻す
            with open(self.master_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            return True

        except Exception as e:
            logger.error(f"ステージ更新中にエラーが発生: {e}", exc_info=True)
            return False

    def update_stage_to_next(self, email: str) -> Optional[str]:
        """
        指定されたメールアドレスのステージを次のステージに進める
        
        Args:
            email: メールアドレス
        
        Returns:
            新しいステージ（完了時はNone）
        """
        current_stage = self.get_stage(email)
        if current_stage is None:
            logger.warning(f"メールアドレスのステージを取得できませんでした: {email}")
            return None

        next_stage = NEXT_STAGE.get(current_stage)
        if next_stage is None:
            logger.info(f"ステージが完了しています: {email} (stage: {current_stage})")
            return None

        if self.update_stage(email, next_stage):
            return next_stage
        return None

    def get_stage(self, email: str) -> Optional[str]:
        """
        指定されたメールアドレスの現在のステージを取得
        
        Args:
            email: メールアドレス
        
        Returns:
            現在のステージ（見つからない場合はNone）
        """
        try:
            with open(self.master_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("email", "").strip().lower() == email.lower():
                        return row.get("stage", "initial").strip()
            return None
        except Exception as e:
            logger.error(f"ステージ取得中にエラーが発生: {e}", exc_info=True)
            return None

    def get_recipients_by_stage(self, stage: str) -> List[Dict[str, str]]:
        """
        指定されたステージのレシピエントを取得
        
        Args:
            stage: ステージ（initial, follow1, follow2, follow3, completed）
        
        Returns:
            レシピエントのリスト
        """
        recipients = []
        try:
            with open(self.master_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("stage", "initial").strip() == stage:
                        recipients.append({
                            "email": row.get("email", "").strip(),
                            "company_name": row.get("company_name", "").strip(),
                            "address": row.get("address", "").strip(),
                            "stage": row.get("stage", "initial").strip(),
                        })
            return recipients
        except Exception as e:
            logger.error(f"レシピエント取得中にエラーが発生: {e}", exc_info=True)
            return []

    def get_all_recipients(self) -> List[Dict[str, str]]:
        """
        すべてのレシピエントを取得
        
        Returns:
            レシピエントのリスト
        """
        recipients = []
        try:
            with open(self.master_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    recipients.append({
                        "email": row.get("email", "").strip(),
                        "company_name": row.get("company_name", "").strip(),
                        "address": row.get("address", "").strip(),
                        "stage": row.get("stage", "initial").strip(),
                    })
            return recipients
        except Exception as e:
            logger.error(f"レシピエント取得中にエラーが発生: {e}", exc_info=True)
            return []


def update_stage(email: str, new_stage: str, master_file: Optional[Path] = None) -> bool:
    """
    ステージを更新する便利関数
    
    Args:
        email: メールアドレス
        new_stage: 新しいステージ
        master_file: マスターファイルのパス（デフォルト: data/output/master_leads.csv）
    
    Returns:
        更新成功時True、失敗時False
    """
    if master_file is None:
        master_file = Path("data/output/master_leads.csv")
    
    manager = StageManager(master_file)
    return manager.update_stage(email, new_stage)


def update_stage_to_next(email: str, master_file: Optional[Path] = None) -> Optional[str]:
    """
    ステージを次のステージに進める便利関数
    
    Args:
        email: メールアドレス
        master_file: マスターファイルのパス（デフォルト: data/output/master_leads.csv）
    
    Returns:
        新しいステージ（完了時はNone）
    """
    if master_file is None:
        master_file = Path("data/output/master_leads.csv")
    
    manager = StageManager(master_file)
    return manager.update_stage_to_next(email)

