"""
スケジューラーサービス
APSchedulerを使用して定期的にメール送信を実行
"""

import time
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from .main import main as send_emails

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmailSchedulerService:
    """メール送信スケジューラーサービス"""
    
    def __init__(self, hour: int = 9, minute: int = 0):
        """
        スケジューラーを初期化
        
        Args:
            hour: 送信時刻（時、デフォルト: 9時）
            minute: 送信時刻（分、デフォルト: 0分）
        """
        self.scheduler = BackgroundScheduler()
        self.hour = hour
        self.minute = minute
    
    def scheduled_email_send(self):
        """定期的なメール送信処理"""
        try:
            logger.info(f"定期的なメール送信を開始: {datetime.now()}")
            result = send_emails()
            if result == 0:
                logger.info("メール送信が正常に完了しました")
            else:
                logger.warning("メール送信中にエラーが発生しました")
        except Exception as e:
            logger.error(f"メール送信中に予期しないエラーが発生: {e}", exc_info=True)
    
    def start(self):
        """スケジューラーを開始"""
        # 毎日指定時刻にメール送信を実行
        self.scheduler.add_job(
            self.scheduled_email_send,
            trigger=CronTrigger(hour=self.hour, minute=self.minute),
            id='daily_email_send',
            name='毎日のメール送信',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info(f"スケジューラーを開始しました。毎日 {self.hour:02d}:{self.minute:02d} にメール送信を実行します。")
    
    def stop(self):
        """スケジューラーを停止"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("スケジューラーを停止しました")
    
    def run_forever(self):
        """スケジューラーを永続的に実行"""
        try:
            self.start()
            logger.info("スケジューラーが実行中です。Ctrl+Cで停止できます。")
            
            # メインスレッドをブロックしてスケジューラーを実行
            while True:
                time.sleep(60)
        
        except (KeyboardInterrupt, SystemExit):
            logger.info("スケジューラーを停止しています...")
            self.stop()


def main():
    """メインエントリーポイント（スケジューラーサービスとして実行）"""
    import os
    
    # 環境変数から送信時刻を取得（デフォルト: 9:00）
    send_hour = int(os.getenv("EMAIL_SEND_HOUR", "9"))
    send_minute = int(os.getenv("EMAIL_SEND_MINUTE", "0"))
    
    service = EmailSchedulerService(hour=send_hour, minute=send_minute)
    service.run_forever()


if __name__ == "__main__":
    main()

