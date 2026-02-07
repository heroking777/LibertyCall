"""
本番用スケジューラーサービス
営業メール自動送信システム
"""

import logging
import time
import os
import sys
import fcntl
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import List, Dict, Optional

from .csv_repository_prod import load_recipients, save_recipients
from .sendgrid_client import send_email_html, send_notification_email, send_daily_report_email

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 定数
MAX_SEND_PER_DAY = 200
SEND_HOUR = 9
SEND_MINUTE = 0
# ステージごとの送信間隔（初回送信日からの経過日数）
FOLLOWUP1_DAYS = 3   # 初回から3日後にフォローメール1
FOLLOWUP2_DAYS = 8   # 初回から8日後にフォローメール2
FOLLOWUP3_DAYS = 15  # 初回から15日後にフォローメール3

# ロックファイルのパス
LOCK_FILE_PATH = Path(__file__).parent.parent / "logs" / "send_batch.lock"
SCHEDULER_LOCK_FILE_PATH = Path(__file__).parent.parent / "logs" / "scheduler.lock"

# グローバル変数：スケジューラーインスタンス（重複起動防止用）
_scheduler_instance: Optional[BackgroundScheduler] = None


def get_logger(name: str = None):
    """ロガーを取得"""
    return logging.getLogger(name or __name__)


# シミュレーションモード用のフラグ
SIMULATION_MODE = False
SIMULATION_LIMIT = 10  # シミュレーションモードでの送信上限


def simulation_send_email(recipient_email: str, subject: str, body_text: str) -> bool:
    """メール送信をシミュレート（実際には送信しない）"""
    logger.info(f"[SIMULATION] Would send email to {recipient_email}")
    logger.info(f"[SIMULATION] Subject: {subject}")
    logger.info(f"[SIMULATION] Body preview: {body_text[:100]}...")
    return True


def select_recipients_for_today(recipients: List[Dict], limit: int = None) -> List[Dict]:
    """
    今日送信すべきレシピエントを選択
    初回送信日からの経過日数で判定
    
    Args:
        recipients: 全レシピエントのリスト
        limit: 送信上限（Noneの場合はMAX_SEND_PER_DAYを使用）
    
    Returns:
        今日送信すべきレシピエントのリスト
    """
    today = datetime.now().date()
    send_targets = []
    max_limit = limit if limit is not None else MAX_SEND_PER_DAY
    
    for r in recipients:
        stage = r.get("stage", "initial")
        
        # completedステージは除外
        if stage == "completed":
            continue
        
        # 初回送信日を取得
        initial_sent_str = r.get("initial_sent_date", "")
        initial_sent = None
        if initial_sent_str:
            try:
                initial_sent = datetime.strptime(initial_sent_str, "%Y-%m-%d").date()
            except ValueError:
                pass
        
        # 初回送信前（initialステージでinitial_sent_dateが未設定）
        if stage == "initial" and not initial_sent:
            send_targets.append(r)
            if len(send_targets) >= max_limit:
                break
            continue
        
        # 初回送信日が設定されていない場合はスキップ
        if not initial_sent:
            continue
        
        # 初回送信日からの経過日数を計算
        days_since_initial = (today - initial_sent).days
        
        # ステージごとの送信条件をチェック
        should_send = False
        if stage == "initial":
            # 初回は即座に送信（既に送信済みの場合は次へ）
            should_send = False  # initial_sentが設定されている場合は既に送信済み
        elif stage == "follow1":
            # 初回から3日後
            should_send = days_since_initial >= FOLLOWUP1_DAYS
        elif stage == "follow2":
            # 初回から8日後
            should_send = days_since_initial >= FOLLOWUP2_DAYS
        elif stage == "follow3":
            # 初回から15日後
            should_send = days_since_initial >= FOLLOWUP3_DAYS
        
        if should_send:
            send_targets.append(r)
        
        # 上限に達したら終了
        if len(send_targets) >= max_limit:
            break
    
    return send_targets


def get_email_subject_and_template_path(stage: str, recipient: Dict) -> tuple:
    """
    ステージに応じた件名とHTMLテンプレートパスを取得
    
    Args:
        stage: 現在のステージ
        recipient: レシピエント情報
    
    Returns:
        (subject, html_template_path) のタプル
    """
    company_name = recipient.get("company_name", "")
    
    subject_map = {
        "initial": "【人件費削減】電話対応コストを大幅削減する方法",
        "follow1": "【人件費削減のご提案】電話対応コストの見直しについて",
        "follow2": "【人件費削減のご提案】電話対応コストを見直しませんか？",
        "follow3": "【最終のご案内】電話対応コスト削減のご提案（LibertyCall）",
    }
    
    template_map = {
        "initial": "initial.html",
        "follow1": "follow1.html",
        "follow2": "follow2.html",
        "follow3": "follow3.html",
    }
    
    subject = subject_map.get(stage, f"【LibertyCall】ご案内 - {company_name}様")
    template_filename = template_map.get(stage, "initial.html")
    
    # テンプレートディレクトリのパス
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    html_template_path = os.path.join(template_dir, template_filename)
    
    return subject, html_template_path


def send_email_to_recipient(recipient: Dict, use_simulation: bool = False) -> tuple[bool, str]:
    """
    レシピエントにメールを送信（HTMLテンプレート使用）
    
    Args:
        recipient: レシピエント情報
        use_simulation: シミュレーションモード（Trueの場合、実際には送信しない）
    
    Returns:
        (成功フラグ, エラーメッセージ) のタプル
        成功時: (True, "")
        失敗時: (False, "エラーメッセージ")
    """
    email = recipient.get("email", "").strip()
    if not email:
        return False
    
    stage = recipient.get("stage", "initial")
    subject, html_template_path = get_email_subject_and_template_path(stage, recipient)
    
    # テンプレート内の変数を置換するための辞書
    replacements = {
        "[会社名]": recipient.get("company_name", ""),
        "[担当者名]": recipient.get("contact_name", "担当者様"),
        "{company_name}": recipient.get("company_name", ""),
        "{email}": email,
    }
    
    try:
        if use_simulation:
            logger.info(f"[SIMULATION] Would send HTML email to {email}")
            logger.info(f"[SIMULATION] Subject: {subject}")
            logger.info(f"[SIMULATION] Template: {html_template_path}")
            return True, ""
        else:
            success, error_msg = send_email_html(email, subject, html_template_path, replacements)
            return success, error_msg
    except Exception as e:
        error_msg = f"予期しないエラー: {str(e)}"
        logger.error(f"メール送信エラー ({email}): {e}")
        return False, error_msg


def send_batch(simulation: bool = False, limit: int = None):
    """
    バッチ送信処理（二重実行防止機能付き）
    
    Args:
        simulation: シミュレーションモード（Trueの場合、実際には送信しない）
        limit: 送信上限（シミュレーションモード用）
    """
    mode_str = "[SIMULATION]" if simulation else "[PRODUCTION]"
    
    # ロックファイルで二重実行を防止
    lock_file = None
    try:
        # ロックファイルのディレクトリが存在しない場合は作成
        LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # ロックファイルを開く（排他ロック）
        lock_file = open(LOCK_FILE_PATH, 'w')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning(f"送信処理が既に実行中です。二重実行をスキップします。")
            return
        
        logger.info(f"=== {mode_str} Starting daily send batch ===")
        
        # ロックファイルにPIDを記録
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        
    except Exception as e:
        logger.error(f"ロックファイルの作成エラー: {e}")
        if lock_file:
            try:
                lock_file.close()
            except:
                pass
        return
    
    try:
        if simulation:
            logger.info("Running in SIMULATION mode (no emails will be sent)")
        else:
            # SendGrid APIキーの確認
            import os
            if not os.getenv("SENDGRID_API_KEY"):
                logger.error("SENDGRID_API_KEYが設定されていません")
                return
        
        # 送信先リストを読み込み
        recipients = load_recipients()
        logger.info(f"Total recipients loaded: {len(recipients)}")
        
        # 今日送信すべきレシピエントを選択
        send_limit = limit if limit is not None else (SIMULATION_LIMIT if simulation else MAX_SEND_PER_DAY)
        today_targets = select_recipients_for_today(recipients, limit=send_limit)
        logger.info(f"Selected {len(today_targets)} recipients for today (limit: {send_limit})")
        
        if not today_targets:
            logger.info("No recipients to send today")
            logger.info(f"=== {mode_str} End of daily send batch ===")
            return
        
        # メール送信
        sent_count = 0
        failed_count = 0
        sent_emails = []
        emails_to_remove = []  # 永続エラーで削除するメールアドレス
        
        for r in today_targets:
            email = r.get("email", "").strip()
            if not email:
                continue
            
            try:
                success, error_msg = send_email_to_recipient(r, use_simulation=simulation)
                
                if success:
                    # 初回送信の場合はinitial_sent_dateを記録
                    current_stage = r.get("stage", "initial")
                    if current_stage == "initial" and not r.get("initial_sent_date"):
                        r["initial_sent_date"] = datetime.now().strftime("%Y-%m-%d")
                        logger.info(f"Initial send date recorded for {email}: {r['initial_sent_date']}")
                    
                    # ステージを進める
                    if current_stage == "initial":
                        r["stage"] = "follow1"
                    elif current_stage == "follow1":
                        r["stage"] = "follow2"
                    elif current_stage == "follow2":
                        r["stage"] = "follow3"
                    elif current_stage == "follow3":
                        r["stage"] = "completed"
                    
                    # 送信日を更新
                    r["last_sent_date"] = datetime.now().strftime("%Y-%m-%d")
                    sent_count += 1
                    
                    # ログ出力用：初回送信日からの経過日数を計算
                    days_info = "N/A"
                    if r.get("initial_sent_date"):
                        try:
                            initial_date = datetime.strptime(r["initial_sent_date"], "%Y-%m-%d").date()
                            days_info = str((datetime.now().date() - initial_date).days)
                        except ValueError:
                            days_info = "N/A"
                    
                    sent_emails.append(email)
                    logger.info(f"Sent successfully to {email} (stage: {r['stage']}, days since initial: {days_info})")
                else:
                    failed_count += 1
                    # 永続的なエラーの場合は削除リストに追加
                    if error_msg and "永続的なエラー" in error_msg:
                        emails_to_remove.append(email)
                        logger.warning(f"永続的なエラーのため削除: {email} | {error_msg}")
                    else:
                        logger.warning(f"送信失敗: {email} | {error_msg}")
            
            except Exception as e:
                failed_count += 1
                error_msg = f"予期しないエラー: {str(e)}"
                logger.error(f"Error sending to {email}: {e}", exc_info=True)
        
        # 永続エラーのメールアドレスをリストから削除
        if emails_to_remove and not simulation:
            from .csv_repository_prod import ProductionCSVRepository
            repo = ProductionCSVRepository()
            repo.remove_emails(emails_to_remove)
            logger.info(f"永続エラーのメールアドレス {len(emails_to_remove)}件をリストから削除しました")
        
        # 送信先リストを保存（シミュレーションモードでも更新）
        if not simulation:
            save_recipients(recipients)
            logger.info(f"Recipients list updated")
        else:
            logger.info(f"[SIMULATION] Recipients list would be updated (not saved in simulation mode)")
        
        logger.info(f"Batch completed: {sent_count} emails sent, {failed_count} failed")
        
        # 通知メールを送信（シミュレーションモードでは送信しない）
        if not simulation:
            try:
                send_notification_email(
                    sent_count=sent_count,
                    failed_count=failed_count,
                    sent_emails=sent_emails
                )
                logger.info("通知メールを送信しました")
            except Exception as e:
                logger.error(f"通知メール送信エラー: {e}", exc_info=True)
        
        logger.info(f"=== {mode_str} End of daily send batch ===")
    
    except Exception as e:
        logger.error(f"Batch processing error: {e}", exc_info=True)
        # エラー時も通知メールを送信（シミュレーションモードでは送信しない）
        if not simulation:
            try:
                send_notification_email(
                    sent_count=0,
                    failed_count=0,
                    error_message=f"バッチ処理中にエラーが発生しました: {str(e)}"
                )
            except:
                pass
    finally:
        # ロックファイルを解放
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                # ロックファイルを削除
                if LOCK_FILE_PATH.exists():
                    LOCK_FILE_PATH.unlink()
            except Exception as e:
                logger.warning(f"ロックファイルの解放エラー: {e}")


def generate_daily_report():
    """
    日次配信レポートを生成し、メール送信
    また、SendGridイベントログからバウンスしたメールアドレスを自動削除
    """
    try:
        # レポート生成スクリプトのパス
        project_root = Path(__file__).parent.parent.parent
        report_script = project_root / "logs" / "report_generator.py"
        
        if not report_script.exists():
            logger.warning(f"レポート生成スクリプトが見つかりません: {report_script}")
            return
        
        # レポート生成スクリプトを実行
        import subprocess
        result = subprocess.run(
            [sys.executable, str(report_script)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300  # 5分のタイムアウト
        )
        
        if result.returncode == 0:
            logger.info("日次配信レポートを生成しました")
            if result.stdout:
                logger.debug(f"レポート生成出力: {result.stdout}")
            
            # SendGridイベントログからバウンスしたメールアドレスを自動削除
            try:
                from .csv_repository_prod import load_invalid_emails_from_sendgrid, ProductionCSVRepository
                invalid_emails = load_invalid_emails_from_sendgrid()
                if invalid_emails:
                    repo = ProductionCSVRepository()
                    repo.remove_emails(list(invalid_emails))
                    logger.info(f"SendGridイベントログから検出された無効メールアドレス {len(invalid_emails)}件をmaster_leads.csvから削除しました")
                else:
                    logger.debug("削除対象の無効メールアドレスはありませんでした")
            except Exception as e:
                logger.error(f"無効メールアドレスの自動削除エラー: {e}", exc_info=True)
            
            # レポート生成後、メール送信
            try:
                report_csv_path = project_root / "logs" / "sendgrid_report_daily.csv"
                if send_daily_report_email(str(report_csv_path)):
                    logger.info("日次レポートメールを送信しました")
                else:
                    logger.warning("日次レポートメールの送信に失敗しました")
            except Exception as e:
                logger.error(f"日次レポートメール送信エラー: {e}", exc_info=True)
        else:
            logger.error(f"レポート生成に失敗しました: {result.stderr}")
    
    except Exception as e:
        logger.error(f"レポート生成エラー: {e}", exc_info=True)


def start_scheduler(hour: int = None, minute: int = None, simulation: bool = False):
    """
    スケジューラーを開始（重複起動防止機能付き）
    
    Args:
        hour: 送信時刻（時、デフォルト: SEND_HOUR）
        minute: 送信時刻（分、デフォルト: SEND_MINUTE）
        simulation: シミュレーションモード
    
    Returns:
        スケジューラーインスタンス（既に起動している場合は既存のインスタンス）
    """
    global _scheduler_instance
    
    # 既にスケジューラーが起動している場合は既存のインスタンスを返す
    if _scheduler_instance is not None and _scheduler_instance.running:
        logger.warning("スケジューラーは既に起動しています。重複起動をスキップします。")
        return _scheduler_instance
    
    # スケジューラーロックファイルで二重起動を防止
    scheduler_lock_file = None
    try:
        SCHEDULER_LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        scheduler_lock_file = open(SCHEDULER_LOCK_FILE_PATH, 'w')
        try:
            fcntl.flock(scheduler_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("スケジューラーが既に起動しています（ロックファイル検出）。重複起動をスキップします。")
            return _scheduler_instance
        
        scheduler_lock_file.write(str(os.getpid()))
        scheduler_lock_file.flush()
    
    except Exception as e:
        logger.error(f"スケジューラーロックファイルの作成エラー: {e}")
        if scheduler_lock_file:
            try:
                scheduler_lock_file.close()
            except:
                pass
    
    send_hour = hour if hour is not None else SEND_HOUR
    send_minute = minute if minute is not None else SEND_MINUTE
    
    scheduler = BackgroundScheduler()
    
    # 既存のジョブをチェック（念のため）
    existing_jobs = scheduler.get_jobs()
    if existing_jobs:
        logger.warning(f"既存のジョブが {len(existing_jobs)} 件見つかりました。クリアします。")
        for job in existing_jobs:
            scheduler.remove_job(job.id)
    
    # シミュレーションモードの場合はラッパー関数を作成
    if simulation:
        def sim_send_batch():
            send_batch(simulation=True, limit=SIMULATION_LIMIT)
        scheduler.add_job(
            sim_send_batch,
            trigger=CronTrigger(hour=send_hour, minute=send_minute),
            id='daily_email_send',
            name='毎日の営業メール送信（シミュレーション）',
            replace_existing=True
        )
        logger.info("Scheduler started in SIMULATION mode")
    else:
        scheduler.add_job(
            send_batch,
            trigger=CronTrigger(hour=send_hour, minute=send_minute),
            id='daily_email_send',
            name='毎日の営業メール送信',
            replace_existing=True
        )
    
    # レポート生成を毎日1:00に実行（メール送信の後）
    scheduler.add_job(
        generate_daily_report,
        trigger=CronTrigger(hour=1, minute=0),
        id='daily_report_generation',
        name='日次配信レポート生成',
        replace_existing=True
    )
    
    scheduler.start()
    _scheduler_instance = scheduler
    
    logger.info(f"Scheduler started (daily at {send_hour:02d}:{send_minute:02d}, report at 01:00)")
    logger.info(f"Registered jobs: {[job.id for job in scheduler.get_jobs()]}")
    
    return scheduler


def run_forever(hour: int = None, minute: int = None, simulation: bool = False):
    """
    スケジューラーを永続的に実行
    
    Args:
        hour: 送信時刻（時）
        minute: 送信時刻（分）
        simulation: シミュレーションモード
    """
    try:
        scheduler = start_scheduler(hour=hour, minute=minute, simulation=simulation)
        mode_str = "SIMULATION" if simulation else "PRODUCTION"
        logger.info(f"Scheduler is running in {mode_str} mode. Press Ctrl+C to stop.")
        
        # メインスレッドをブロック
        while True:
            time.sleep(60)
    
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping scheduler...")
        if 'scheduler' in locals() and scheduler.running:
            scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    import os
    import sys
    
    # コマンドライン引数からシミュレーションモードを判定
    simulation = "--simulation" in sys.argv or "-s" in sys.argv
    
    # 環境変数から送信時刻を取得
    send_hour = int(os.getenv("EMAIL_SEND_HOUR", str(SEND_HOUR)))
    send_minute = int(os.getenv("EMAIL_SEND_MINUTE", str(SEND_MINUTE)))
    
    if simulation:
        logger.info("=" * 60)
        logger.info("RUNNING IN SIMULATION MODE")
        logger.info("No emails will be sent. This is for testing only.")
        logger.info("=" * 60)
    
    run_forever(hour=send_hour, minute=send_minute, simulation=simulation)
