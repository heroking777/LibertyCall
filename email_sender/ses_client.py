"""
AWS SES クライアント
メール送信機能を提供
"""

import boto3
from botocore.exceptions import ClientError
from typing import Optional, List
import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from .config import Config


class SESClient:
    """AWS SESを使用したメール送信クライアント"""
    
    def __init__(self):
        self.ses_client = boto3.client(
            "ses",
            region_name=Config.AWS_REGION,
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
        )
        self.sender_email = Config.SENDER_EMAIL
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        """
        メールを送信
        
        Args:
            to_email: 送信先メールアドレス
            subject: 件名
            body_text: 本文（テキスト形式）
            body_html: 本文（HTML形式、オプション）
        
        Returns:
            送信成功時True、失敗時False
        """
        try:
            destination = {"ToAddresses": [to_email]}
            
            message = {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            }
            
            if body_html:
                message["Body"]["Html"] = {
                    "Data": body_html,
                    "Charset": "UTF-8",
                }
            
            response = self.ses_client.send_email(
                Source=self.sender_email,
                Destination=destination,
                Message=message,
            )
            
            print(f"メール送信成功: {to_email} (MessageId: {response['MessageId']})")
            return True
        
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            print(f"メール送信失敗: {to_email} - {error_code}: {e}")
            return False
    
    def send_template_email(
        self,
        to_email: str,
        to_name: str,
        template_path: str,
        subject: str,
    ) -> bool:
        """
        テンプレートファイルを使用してメールを送信
        
        Args:
            to_email: 送信先メールアドレス
            to_name: 送信先の名前
            template_path: テンプレートファイルのパス
            subject: 件名
        
        Returns:
            送信成功時True、失敗時False
        """
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()
            
            # テンプレート内の変数を置換
            body_text = template_content.replace("{name}", to_name)
            
            return self.send_email(to_email, subject, body_text)
        
        except FileNotFoundError:
            print(f"テンプレートファイルが見つかりません: {template_path}")
            return False
        except Exception as e:
            print(f"テンプレート読み込みエラー: {e}")
            return False
    
    def send_email_with_attachment(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> bool:
        """
        添付ファイル付きメールを送信
        
        Args:
            to_email: 送信先メールアドレス
            subject: 件名
            body_text: 本文（テキスト形式）
            body_html: 本文（HTML形式、オプション）
            attachments: 添付ファイルのリスト [{"filename": "file.pdf", "path": "/path/to/file.pdf"}]
        
        Returns:
            送信成功時True、失敗時False
        """
        try:
            # MIMEメッセージを作成
            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = to_email
            
            # 本文を追加
            msg_body = MIMEMultipart("alternative")
            msg_body.attach(MIMEText(body_text, "plain", "utf-8"))
            if body_html:
                msg_body.attach(MIMEText(body_html, "html", "utf-8"))
            msg.attach(msg_body)
            
            # 添付ファイルを追加
            if attachments:
                for attachment in attachments:
                    if "path" in attachment and os.path.exists(attachment["path"]):
                        filename = attachment.get("filename", os.path.basename(attachment["path"]))
                        with open(attachment["path"], "rb") as f:
                            part = MIMEApplication(f.read())
                            part.add_header(
                                "Content-Disposition",
                                "attachment",
                                filename=filename,
                            )
                            msg.attach(part)
            
            # Rawメッセージとして送信
            raw_message = {
                "Data": msg.as_string(),
            }
            
            response = self.ses_client.send_raw_email(
                Source=self.sender_email,
                Destinations=[to_email],
                RawMessage=raw_message,
            )
            
            print(f"メール送信成功（添付付き）: {to_email} (MessageId: {response['MessageId']})")
            return True
        
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            print(f"メール送信失敗: {to_email} - {error_code}: {e}")
            return False
        except Exception as e:
            print(f"メール送信エラー: {to_email} - {e}")
            return False

