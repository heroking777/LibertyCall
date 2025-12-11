"""
設定管理モジュール
環境変数から設定を読み込む
"""

import os
from dotenv import load_dotenv

# .envファイルを読み込む（絶対パスで指定、Webルート外）
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    """アプリケーション設定クラス"""
    
    # AWS設定
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    
    # 送信設定
    DAILY_SEND_LIMIT = int(os.getenv("DAILY_SEND_LIMIT", "200"))  # 本番仕様: 200件
    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
    
    # フォローアップ間隔（日数）
    FOLLOWUP1_DAYS_AFTER = int(os.getenv("FOLLOWUP1_DAYS_AFTER", "7"))
    FOLLOWUP2_DAYS_AFTER = int(os.getenv("FOLLOWUP2_DAYS_AFTER", "7"))
    FOLLOWUP3_DAYS_AFTER = int(os.getenv("FOLLOWUP3_DAYS_AFTER", "7"))
    
    # CSVファイルパス
    RECIPIENTS_CSV_PATH = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "recipients.csv"
    )
    
    # テンプレートディレクトリ
    TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
    
    @classmethod
    def validate(cls):
        """設定値の検証"""
        required_vars = [
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "SENDER_EMAIL",
        ]
        
        missing = []
        for var in required_vars:
            value = getattr(cls, var)
            if not value:
                missing.append(var)
        
        if missing:
            raise ValueError(
                f"以下の環境変数が設定されていません: {', '.join(missing)}"
            )

