#!/usr/bin/env python3
"""
21時に100件送信するバッチスクリプト
"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from email_sender.csv_repository_prod import load_recipients, save_recipients, ProductionCSVRepository
from email_sender.sendgrid_client import send_email_html, send_notification_email
from datetime import datetime
import logging

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_email_subject_and_template_path(stage: str):
    """ステージに応じた件名とHTMLテンプレートパスを取得"""
    subject_map = {
        "initial": "【人件費削減】電話対応コストを80％カットする方法",
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
    
    subject = subject_map.get(stage, "【LibertyCall】ご案内")
    template_filename = template_map.get(stage, "initial.html")
    
    # テンプレートディレクトリのパス
    template_dir = project_root / "email_sender" / "templates"
    html_template_path = template_dir / template_filename
    
    return subject, str(html_template_path)


def send_batch_100():
    """100件送信バッチ"""
    logger.info("=== Starting 21:00 batch send (100 recipients) ===")
    
    try:
        # 送信先リストを読み込み
        recipients = load_recipients()
        logger.info(f"Total recipients loaded: {len(recipients)}")
        
        # 上から100件を選択（stageがcompletedでないもの）
        send_targets = []
        for r in recipients:
            if len(send_targets) >= 100:
                break
            stage = r.get("stage", "initial")
            if stage != "completed":
                send_targets.append(r)
        
        logger.info(f"Selected {len(send_targets)} recipients for sending")
        
        if not send_targets:
            logger.info("No recipients to send")
            return
        
        # メール送信
        sent_count = 0
        failed_count = 0
        sent_emails = []
        emails_to_remove = []  # 永続エラーで削除するメールアドレス
        
        for r in send_targets:
            email = r.get("email", "").strip()
            if not email:
                continue
            
            try:
                stage = r.get("stage", "initial")
                subject, html_template_path = get_email_subject_and_template_path(stage)
                
                # テンプレート内の変数を置換
                replacements = {
                    "[会社名]": r.get("company_name", ""),
                    "[担当者名]": r.get("contact_name", "担当者様"),
                    "{company_name}": r.get("company_name", ""),
                    "{email}": email
                }
                
                # メール送信
                success, error_msg = send_email_html(email, subject, html_template_path, replacements)
                
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
                    sent_emails.append(email)
                    logger.info(f"Sent successfully to {email} (stage: {r['stage']})")
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
        if emails_to_remove:
            repo = ProductionCSVRepository()
            repo.remove_emails(emails_to_remove)
            logger.info(f"永続エラーのメールアドレス {len(emails_to_remove)}件をリストから削除しました")
        
        # 送信先リストを保存
        save_recipients(recipients)
        logger.info(f"Recipients list updated")
        
        logger.info(f"Batch completed: {sent_count} emails sent, {failed_count} failed")
        
        # 通知メールを送信
        try:
            send_notification_email(
                sent_count=sent_count,
                failed_count=failed_count
            )
            logger.info("通知メールを送信しました")
        except Exception as e:
            logger.error(f"通知メール送信エラー: {e}", exc_info=True)
        
        logger.info(f"=== End of 21:00 batch send ===")
        
    except Exception as e:
        logger.error(f"予期しないエラー: {e}", exc_info=True)
        # エラー時も通知メールを送信
        try:
            send_notification_email(
                sent_count=0,
                failed_count=0,
                error_message=f"バッチ処理中にエラーが発生しました: {str(e)}"
            )
        except:
            pass


if __name__ == "__main__":
    send_batch_100()

