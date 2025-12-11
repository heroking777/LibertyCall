"""
メインエントリーポイント
毎日このスクリプトを実行してメール送信を行う
"""

import sys
from .config import Config
from .csv_repository import CSVRepository
from .ses_client import SESClient
from .scheduler import Scheduler


def get_template_path(stage: str) -> str:
    """ステージに対応するテンプレートファイルのパスを取得"""
    template_map = {
        "initial": "initial_email.txt",
        "followup1": "followup_1.txt",
        "followup2": "followup_2.txt",
        "followup3": "followup_3.txt",
    }
    
    template_filename = template_map.get(stage)
    if not template_filename:
        raise ValueError(f"不明なステージ: {stage}")
    
    import os
    return os.path.join(Config.TEMPLATES_DIR, template_filename)


def get_subject(stage: str) -> str:
    """ステージに対応する件名を取得"""
    subject_map = {
        "initial": "初回ご案内",
        "followup1": "フォローアップ（1回目）",
        "followup2": "フォローアップ（2回目）",
        "followup3": "フォローアップ（3回目）",
    }
    
    return subject_map.get(stage, "お知らせ")


def main():
    """メイン処理"""
    try:
        # 設定の検証
        Config.validate()
        
        # リポジトリとクライアントの初期化
        repository = CSVRepository()
        ses_client = SESClient()
        scheduler = Scheduler()
        
        # 全レシピエントを読み込み
        recipients = repository.read_all()
        print(f"レシピエント総数: {len(recipients)}")
        
        # 配信停止済みを除外
        recipients = repository.filter_unsubscribed(recipients)
        print(f"配信停止除外後: {len(recipients)}件")
        
        # 送信すべきレシピエントを取得
        to_send = scheduler.get_recipients_to_send(
            recipients, limit=Config.DAILY_SEND_LIMIT
        )
        print(f"送信対象: {len(to_send)}件")
        
        # メール送信
        success_count = 0
        fail_count = 0
        
        for recipient, stage in to_send:
            template_path = get_template_path(stage)
            subject = get_subject(stage)
            
            # メール送信
            success = ses_client.send_template_email(
                to_email=recipient.email,
                to_name=recipient.name,
                template_path=template_path,
                subject=subject,
            )
            
            if success:
                # 送信日時を更新
                recipient.update_sent_at(stage)
                repository.save(recipient)
                success_count += 1
            else:
                fail_count += 1
        
        print(f"\n送信完了: 成功 {success_count}件, 失敗 {fail_count}件")
        
        return 0 if fail_count == 0 else 1
    
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"予期しないエラー: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

