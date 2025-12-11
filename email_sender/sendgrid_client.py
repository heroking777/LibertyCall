"""
SendGrid クライアント
SendGrid経由でメール送信を行う
"""

import os
import base64
from typing import List, Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, TrackingSettings, ClickTracking
from dotenv import load_dotenv
from pathlib import Path

# .envファイルを読み込む（絶対パスで指定、Webルート外）
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "sales@libcall.com")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")  # 通知先メールアドレス


def send_email(recipient_email: str, subject: str, body_text: str) -> bool:
    """
    SendGrid経由でメール送信（テキスト形式）
    
    Args:
        recipient_email: 送信先メールアドレス
        subject: 件名
        body_text: 本文（テキスト形式）
    
    Returns:
        送信成功時True、失敗時False
    """
    if not SENDGRID_API_KEY:
        print("エラー: SENDGRID_API_KEYが設定されていません")
        return False
    
    if not SENDER_EMAIL:
        print("エラー: SENDER_EMAILが設定されていません")
        return False
    
    message = Mail(
        from_email=SENDER_EMAIL,
        to_emails=recipient_email,
        subject=subject,
        plain_text_content=body_text
    )
    
    # クリックトラッキングを無効化（URLをそのまま表示）
    tracking_settings = TrackingSettings()
    click_tracking = ClickTracking(enable=False)
    tracking_settings.click_tracking = click_tracking
    message.tracking_settings = tracking_settings
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"送信成功: {recipient_email} | ステータス: {response.status_code}")
        return True
    except Exception as e:
        print(f"送信失敗: {recipient_email} | 理由: {str(e)}")
        return False


def send_email_html(recipient_email: str, subject: str, html_path: str, replacements: dict = None) -> tuple[bool, str]:
    """
    SendGrid経由でHTMLテンプレートを送信
    
    Args:
        recipient_email: 送信先メールアドレス
        subject: 件名
        html_path: HTMLテンプレートファイルのパス
        replacements: テンプレート内の変数を置換する辞書（例: {"{company_name}": "株式会社ABC"}）
    
    Returns:
        (成功フラグ, エラーメッセージ) のタプル
        成功時: (True, "")
        失敗時: (False, "エラーメッセージ")
    """
    if not SENDGRID_API_KEY:
        error_msg = "SENDGRID_API_KEYが設定されていません"
        print(f"エラー: {error_msg}")
        return False, error_msg
    
    if not SENDER_EMAIL:
        error_msg = "SENDER_EMAILが設定されていません"
        print(f"エラー: {error_msg}")
        return False, error_msg
    
    import os
    if not os.path.exists(html_path):
        error_msg = f"HTMLテンプレートファイルが見つかりません: {html_path}"
        print(f"エラー: {error_msg}")
        return False, error_msg
    
    try:
        # HTMLテンプレートを読み込む
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        # 変数を置換
        if replacements:
            for key, value in replacements.items():
                html_content = html_content.replace(key, str(value))
        
        # 差出人名をここで指定（固定）
        from_email = f"LibertyCall サポート <{SENDER_EMAIL}>"
        
        message = Mail(
            from_email=from_email,
            to_emails=recipient_email,
            subject=subject,
            html_content=html_content
        )
        
        # クリックトラッキングを無効化（URLをそのまま表示）
        tracking_settings = TrackingSettings()
        click_tracking = ClickTracking(enable=False)
        tracking_settings.click_tracking = click_tracking
        message.tracking_settings = tracking_settings
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"送信成功: {recipient_email} | ステータス: {response.status_code}")
        return True, ""
    except Exception as e:
        # SendGridのエラー詳細を取得
        error_msg = str(e)
        error_type = "不明なエラー"
        
        # SendGridのHTTPErrorから詳細を取得
        if hasattr(e, 'body'):
            try:
                import json
                error_body = json.loads(e.body) if isinstance(e.body, str) else e.body
                if isinstance(error_body, dict):
                    if 'errors' in error_body and len(error_body['errors']) > 0:
                        first_error = error_body['errors'][0]
                        error_msg = first_error.get('message', error_msg)
                        error_type = first_error.get('field', '')
            except:
                pass
        
        # エラーの種類を判定
        error_category = "一時的なエラー"
        error_lower = error_msg.lower()
        
        # 永続的なエラー（メールアドレスが無効）
        if any(keyword in error_lower for keyword in [
            'invalid email', 'invalid recipient', 'bounce', 'suppressed',
            'unsubscribed', 'spam report', 'invalid address', 'does not exist',
            'no such user', 'mailbox full', 'user unknown', 'address rejected'
        ]):
            error_category = "永続的なエラー（無効なメールアドレス）"
        # 一時的なエラー（ネットワーク、レート制限など）
        elif any(keyword in error_lower for keyword in [
            'rate limit', 'too many requests', 'timeout', 'connection',
            'network', 'temporary', 'retry', 'service unavailable'
        ]):
            error_category = "一時的なエラー（再試行可能）"
        # APIキーや認証エラー
        elif any(keyword in error_lower for keyword in [
            'unauthorized', 'forbidden', 'api key', 'authentication'
        ]):
            error_category = "設定エラー（APIキーなど）"
        
        full_error_msg = f"{error_category}: {error_msg}"
        print(f"送信失敗: {recipient_email} | {full_error_msg}")
        return False, full_error_msg


def send_email_with_attachment(
    recipient_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    attachments: Optional[List[dict]] = None
) -> bool:
    """
    SendGrid経由で添付ファイル付きメールを送信
    
    Args:
        recipient_email: 送信先メールアドレス
        subject: 件名
        body_text: 本文（テキスト形式）
        body_html: 本文（HTML形式、オプション）
        attachments: 添付ファイルのリスト [{"filename": "file.pdf", "path": "/path/to/file.pdf"}]
    
    Returns:
        送信成功時True、失敗時False
    """
    if not SENDGRID_API_KEY:
        print("エラー: SENDGRID_API_KEYが設定されていません")
        return False
    
    if not SENDER_EMAIL:
        print("エラー: SENDER_EMAILが設定されていません")
        return False
    
    try:
        message = Mail(
            from_email=SENDER_EMAIL,
            to_emails=recipient_email,
            subject=subject,
            plain_text_content=body_text
        )
        
        # クリックトラッキングを無効化（URLをそのまま表示）
        tracking_settings = TrackingSettings()
        click_tracking = ClickTracking(enable=False)
        tracking_settings.click_tracking = click_tracking
        message.tracking_settings = tracking_settings
        
        # HTML本文がある場合は追加
        if body_html:
            message.content = []
            message.add_content(body_text, "text/plain")
            message.add_content(body_html, "text/html")
        
        # 添付ファイルを追加
        if attachments:
            for attachment_info in attachments:
                if "path" in attachment_info and os.path.exists(attachment_info["path"]):
                    filename = attachment_info.get("filename", os.path.basename(attachment_info["path"]))
                    
                    with open(attachment_info["path"], "rb") as f:
                        file_data = f.read()
                    
                    # SendGridではbase64エンコードが必要
                    encoded_file = base64.b64encode(file_data).decode()
                    
                    attachment = Attachment()
                    attachment.file_content = encoded_file
                    attachment.file_type = "application/pdf"  # PDFファイルを想定
                    attachment.file_name = filename
                    attachment.disposition = "attachment"
                    
                    message.add_attachment(attachment)
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"送信成功: {recipient_email} | ステータス: {response.status_code}")
        return True
    except Exception as e:
        print(f"送信失敗: {recipient_email} | 理由: {str(e)}")
        return False


def send_daily_report_email(report_csv_path: str = None) -> bool:
    """
    日次配信レポートをメール送信
    
    Args:
        report_csv_path: レポートCSVファイルのパス（デフォルト: logs/sendgrid_report_daily.csv）
    
    Returns:
        送信成功時True、失敗時False
    """
    if not NOTIFICATION_EMAIL:
        print("通知先メールアドレスが設定されていません（NOTIFICATION_EMAIL）")
        return False
    
    if not SENDGRID_API_KEY:
        print("エラー: SENDGRID_API_KEYが設定されていません")
        return False
    
    if not SENDER_EMAIL:
        print("エラー: SENDER_EMAILが設定されていません")
        return False
    
    from pathlib import Path
    import csv
    
    # レポートCSVファイルのパスを決定
    if report_csv_path:
        report_path = Path(report_csv_path)
    else:
        project_root = Path(__file__).parent.parent
        report_path = project_root / "logs" / "sendgrid_report_daily.csv"
    
    if not report_path.exists():
        print(f"レポートファイルが見つかりません: {report_path}")
        return False
    
    # レポートCSVの最新行を読み込む
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                print("レポートデータがありません")
                return False
            
            # 最新行（最後の行）を取得
            latest_report = rows[-1]
    except Exception as e:
        print(f"レポートファイルの読み込みエラー: {e}")
        return False
    
    # 件名と本文を作成
    report_date = latest_report.get("date", "")
    subject = f"LibertyCall 日次レポート（{report_date}）"
    
    total_sent = latest_report.get("total_sent", "0")
    delivered = latest_report.get("delivered", "0")
    opened = latest_report.get("opened", "0")
    bounced = latest_report.get("bounced", "0")
    auto_replies = latest_report.get("auto_replies", "0")
    delivery_rate = latest_report.get("delivery_rate", "0.0")
    open_rate = latest_report.get("open_rate", "0.0")
    
    body_lines = [
        "LibertyCall 日次配信レポート",
        "",
        f"日付：{report_date}",
        "",
        "=== 配信統計 ===",
        f"総送信数：{total_sent}件",
        f"配信成功：{delivered}件",
        f"開封数：{opened}件",
        f"バウンス：{bounced}件",
        f"自動返信：{auto_replies}件",
        "",
        "=== レート ===",
        f"配信成功率：{delivery_rate}%",
        f"開封率：{open_rate}%",
        "",
        "---",
        "LibertyCall メール送信システム"
    ]
    
    body_text = "\n".join(body_lines)
    
    from_email = f"LibertyCall サポート <{SENDER_EMAIL}>"
    
    message = Mail(
        from_email=from_email,
        to_emails=NOTIFICATION_EMAIL,
        subject=subject,
        plain_text_content=body_text
    )
    
    tracking_settings = TrackingSettings()
    click_tracking = ClickTracking(enable=False)
    tracking_settings.click_tracking = click_tracking
    message.tracking_settings = tracking_settings
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"日次レポートメール送信成功: {NOTIFICATION_EMAIL} | ステータス: {response.status_code}")
        return True
    except Exception as e:
        print(f"日次レポートメール送信失敗: {NOTIFICATION_EMAIL} | 理由: {str(e)}")
        return False


def send_notification_email(
    sent_count: int,
    failed_count: int,
    sent_emails: List[str] = None,
    failed_emails: List[str] = None,
    error_message: str = None
) -> bool:
    """
    メール送信結果の通知メールを送信
    
    Args:
        sent_count: 送信成功数
        failed_count: 送信失敗数
        sent_emails: 送信成功したメールアドレスのリスト（オプション）
        failed_emails: 送信失敗したメールアドレスのリスト（オプション）
        error_message: エラーメッセージ（オプション）
    
    Returns:
        送信成功時True、失敗時False
    """
    if not NOTIFICATION_EMAIL:
        print("通知先メールアドレスが設定されていません（NOTIFICATION_EMAIL）")
        return False
    
    if not SENDGRID_API_KEY:
        print("エラー: SENDGRID_API_KEYが設定されていません")
        return False
    
    if not SENDER_EMAIL:
        print("エラー: SENDER_EMAILが設定されていません")
        return False
    
    from datetime import datetime
    
    # 件名
    subject = f"【LibertyCall】メール送信結果報告 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    # 本文を作成（シンプルに）
    total_count = sent_count + failed_count
    body_lines = [
        "LibertyCall メール送信システム",
        "",
        f"送信日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
        "",
        "=== 送信結果 ===",
        f"送信件数: {total_count}件",
        f"成功: {sent_count}件",
        f"失敗: {failed_count}件",
        "",
        "---",
        "LibertyCall メール送信システム"
    ]
    
    # エラーメッセージ（システムエラーの場合のみ）
    if error_message:
        body_lines.insert(-2, "")
        body_lines.insert(-2, "=== システムエラー ===")
        body_lines.insert(-2, error_message)
    
    body_text = "\n".join(body_lines)
    
    # メール送信
    from_email = f"LibertyCall サポート <{SENDER_EMAIL}>"
    
    message = Mail(
        from_email=from_email,
        to_emails=NOTIFICATION_EMAIL,
        subject=subject,
        plain_text_content=body_text
    )
    
    # クリックトラッキングを無効化
    tracking_settings = TrackingSettings()
    click_tracking = ClickTracking(enable=False)
    tracking_settings.click_tracking = click_tracking
    message.tracking_settings = tracking_settings
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"通知メール送信成功: {NOTIFICATION_EMAIL} | ステータス: {response.status_code}")
        return True
    except Exception as e:
        print(f"通知メール送信失敗: {NOTIFICATION_EMAIL} | 理由: {str(e)}")
        return False
