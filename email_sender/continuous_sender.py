"""
24時間ランダム間隔の分散送信デーモン
常駐プロセスとして24時間稼働し、ランダム間隔でメールを送信
"""

import time
import random
import signal
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# ロギング設定
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from email_sender.scheduler_service_prod import load_recipients, send_email_to_recipient, save_recipients, select_recipients_for_today
from email_sender.sendgrid_analytics import load_daily_limit, update_daily_limit_automatically, save_daily_limit, _load_current_limit_raw


class ContinuousSender:
    """24時間分散送信デーモン"""
    
    def __init__(self, max_daily_limit: int = 5000):
        self.max_daily_limit = max_daily_limit
        self.daily_limit = 50  # 初期値
        self.sent_today = 0
        self.current_date = datetime.now().date()
        self.running = True
        self.last_save_time = datetime.now()
        
        # シグナルハンドラ設定
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """シグナルハンドラ"""
        logger.info(f"シグナル {signum} を受信、シャットダウン中...")
        self.running = False
    
    def calculate_random_interval(self, daily_limit: int) -> float:
        """
        日の送信上限からランダム間隔を計算
        
        Args:
            daily_limit: 1日の送信上限
        
        Returns:
            待機時間（秒）
        """
        if daily_limit <= 0:
            return 3600  # 1時間（安全策）
        
        # 平均間隔を計算（24時間 = 86400秒）
        avg_interval = 86400 / daily_limit
        
        # ±40%のランダム幅を設定
        min_interval = avg_interval * 0.6
        max_interval = avg_interval * 1.4
        
        # ランダムな間隔を生成
        random_interval = random.uniform(min_interval, max_interval)
        
        logger.debug(f"送信間隔: {random_interval:.1f}秒（平均: {avg_interval:.1f}秒）")
        
        return random_interval
    
    def get_next_recipient(self, recipients: List[Dict]) -> Optional[Dict]:
        """
        次に送信すべきレシピエントを選択（修正済みlimitバグ対応版）
        
        Args:
            recipients: 全レシピエントのリスト
        
        Returns:
            次のレシピエント、いない場合はNone
        """
        # 今日の送信残数を計算
        remaining_limit = self.daily_limit - self.sent_today
        
        if remaining_limit <= 0:
            return None
        
        # 修正済みのselect_recipients_for_todayを使用
        candidates = select_recipients_for_today(recipients, limit=remaining_limit)
        
        return candidates[0] if candidates else None
    
    def send_single_email(self, recipient: Dict) -> bool:
        """
        単一メールを送信
        
        Args:
            recipient: レシピエント情報
        
        Returns:
            送信成功時True、失敗時False
        """
        email = recipient.get("email", "").strip()
        if not email:
            return False
        
        # 除外フラグがある場合はスキップ
        if recipient.get("除外", "").strip():
            return False
        try:
            success, error_msg = send_email_to_recipient(recipient, use_simulation=False)
            
            if success:
                # 初回送信の場合はinitial_sent_dateを記録
                current_stage = recipient.get("stage", "initial")
                if current_stage == "initial" and not recipient.get("initial_sent_date"):
                    recipient["initial_sent_date"] = datetime.now().strftime("%Y-%m-%d")
                    logger.info(f"初回送信日を記録: {email}")
                
                # ステージを進める
                if current_stage == "initial":
                    recipient["stage"] = "follow1"
                elif current_stage == "follow1":
                    recipient["stage"] = "follow2"
                elif current_stage == "follow2":
                    recipient["stage"] = "follow3"
                elif current_stage == "follow3":
                    recipient["stage"] = "completed"
                
                # 送信日を更新
                recipient["last_sent_date"] = datetime.now().strftime("%Y-%m-%d")
                
                self.sent_today += 1
                logger.info(f"送信成功: {email} (今日の送信数: {self.sent_today}/{self.daily_limit})")
                
                return True
            else:
                logger.error(f"送信失敗: {email} - {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"送信エラー: {email} - {e}")
            return False
    
    def save_progress(self, recipients: List[Dict]) -> None:
        """進捗を保存"""
        try:
            save_recipients(recipients)
            self.last_save_time = datetime.now()
            logger.debug("進捗を保存しました")
        except Exception as e:
            logger.error(f"進捗保存エラー: {e}")
    
    def check_daily_reset(self) -> None:
        """日付変更をチェックしてリセット"""
        current_date = datetime.now().date()
        
        if current_date != self.current_date:
            logger.info(f"日付が変更: {self.current_date} → {current_date}")
            
            # 新しい日の送信上限を更新
            self.daily_limit = update_daily_limit_automatically()
            
            # カウンターをリセット
            self.sent_today = 0
            self.current_date = current_date
            
            logger.info(f"新しい送信上限: {self.daily_limit}件")
    
    def run(self) -> None:
        """メイン実行ループ"""
        logger.info("=== 24時間分散送信デーモンを開始 ===")
        
        # 初期送信上限を設定（日付チェックなしで現在の値を読む）
        self.daily_limit = _load_current_limit_raw()
        if self.daily_limit is None:
            self.daily_limit = 50
            save_daily_limit(self.daily_limit)
        
        logger.info(f"初期送信上限: {self.daily_limit}件/日")
        
        # レシピエントリストを読み込み
        recipients = load_recipients()
        logger.info(f"レシピエント数: {len(recipients)}件")
        
        while self.running:
            try:
                # 日付変更をチェック
                self.check_daily_reset()
                
                # 送信上限チェック
                if self.sent_today >= self.daily_limit:
                    logger.info(f"今日の送信上限に達しました: {self.sent_today}/{self.daily_limit}")
                    # 1時間待機して再チェック
                    time.sleep(3600)
                    continue
                
                # 次のレシピエントを取得
                next_recipient = self.get_next_recipient(recipients)
                
                if next_recipient is None:
                    logger.info("送信対象がありません。1時間待機...")
                    time.sleep(3600)
                    continue
                
                # メールを送信
                success = self.send_single_email(next_recipient)
                
                # 進捗を保存（5分ごとまたは送信成功時）
                if success or (datetime.now() - self.last_save_time).seconds >= 300:
                    self.save_progress(recipients)
                
                # 次の送信までランダム間隔で待機
                if self.running and self.sent_today < self.daily_limit:
                    interval = self.calculate_random_interval(self.daily_limit)
                    logger.info(f"次の送信まで {interval/60:.1f} 分待機...")
                    
                    # 待機中もシグナルチェック
                    start_time = time.time()
                    while time.time() - start_time < interval and self.running:
                        time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("キーボード割り込みを検出")
                break
            except Exception as e:
                logger.error(f"実行エラー: {e}")
                time.sleep(60)  # エラー時は1分待機
        
        # 終了処理
        logger.info("=== シャットダウン中 ===")
        self.save_progress(recipients)
        logger.info("=== 24時間分散送信デーモンを終了 ===")


if __name__ == "__main__":
    # コマンドライン引数で最大送信上限を設定
    max_limit = 5000
    if len(sys.argv) > 1:
        try:
            max_limit = int(sys.argv[1])
        except ValueError:
            logger.warning(f"無効な引数: {sys.argv[1]}、デフォルト値を使用")
    
    sender = ContinuousSender(max_daily_limit=max_limit)
    sender.run()
