"""
master_leads.csvの指定行にメールを送信するテストスクリプト
"""

import csv
import sys
import os
from pathlib import Path
from typing import Dict

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from email_sender.sendgrid_client import send_email_html
from email_sender.csv_repository_prod import ProductionCSVRepository
from datetime import datetime

def get_email_subject_and_template_path(stage: str, recipient: Dict) -> tuple:
    """
    ステージに応じた件名とHTMLテンプレートパスを取得
    """
    company_name = recipient.get("company_name", "")
    
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
    
    subject = subject_map.get(stage, f"【LibertyCall】ご案内 - {company_name}様")
    template_filename = template_map.get(stage, "initial.html")
    
    # テンプレートディレクトリのパス
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    html_template_path = os.path.join(template_dir, template_filename)
    
    return subject, html_template_path


def send_email_to_recipient(recipient: Dict, use_simulation: bool = False) -> bool:
    """
    レシピエントにメールを送信（HTMLテンプレート使用）
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
            print(f"[SIMULATION] Would send HTML email to {email}")
            print(f"[SIMULATION] Subject: {subject}")
            print(f"[SIMULATION] Template: {html_template_path}")
            return True
        else:
            success = send_email_html(email, subject, html_template_path, replacements)
            return success
    except Exception as e:
        print(f"メール送信エラー ({email}): {e}")
        return False


def send_emails_from_master_leads(csv_path: str, start_line: int, end_line: int, simulation: bool = False):
    """
    master_leads.csvの指定行にメールを送信
    
    Args:
        csv_path: master_leads.csvのパス
        start_line: 開始行（1ベース、ヘッダー含む）
        end_line: 終了行（1ベース、ヘッダー含む）
        simulation: シミュレーションモード
    """
    recipients = []
    
    # CSVファイルを読み込む
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # ヘッダーを除いて2行目から
            if start_line <= i <= end_line:
                email = row.get("email", "").strip() if row.get("email") else ""
                company_name = row.get("company_name", "").strip() if row.get("company_name") else ""
                address = row.get("address", "").strip() if row.get("address") else ""
                stage = row.get("stage", "initial")
                if stage:
                    stage = stage.strip()
                else:
                    stage = "initial"
                
                # メールアドレスが有効かチェック（@が含まれているか）
                if not email or "@" not in email:
                    print(f"警告: 行{i}に有効なメールアドレスがありません: {email}")
                    continue
                
                recipient = {
                    "email": email,
                    "company_name": company_name,
                    "address": address,
                    "stage": stage,
                }
                recipients.append(recipient)
                print(f"読み込み: 行{i} - {email} ({company_name})")
    
    if not recipients:
        print("送信対象がありません")
        return
    
    print(f"\n送信対象: {len(recipients)}件")
    if simulation:
        print("*** シミュレーションモード: 実際には送信しません ***\n")
    else:
        print("*** 本番モード: 実際にメールを送信します ***\n")
    
    # メール送信
    success_count = 0
    fail_count = 0
    updated_recipients = []
    
    for recipient in recipients:
        email = recipient["email"]
        company_name = recipient["company_name"]
        
        print(f"送信中: {email} ({company_name})...")
        success = send_email_to_recipient(recipient, use_simulation=simulation)
        
        if success:
            # ステージを進める
            current_stage = recipient.get("stage", "initial")
            if current_stage == "initial":
                recipient["stage"] = "follow1"
            elif current_stage == "follow1":
                recipient["stage"] = "follow2"
            elif current_stage == "follow2":
                recipient["stage"] = "follow3"
            elif current_stage == "follow3":
                recipient["stage"] = "completed"
            
            # 送信日を更新（master_leads.csvにはlast_sent_dateフィールドがないので、ここでは保持のみ）
            recipient["last_sent_date"] = datetime.now().strftime("%Y-%m-%d")
            # addressフィールドは既に読み込まれているので、そのまま保持
            
            updated_recipients.append(recipient)
            success_count += 1
            print(f"✓ 送信成功: {email} (stage: {recipient['stage']})\n")
        else:
            fail_count += 1
            print(f"✗ 送信失敗: {email}\n")
    
    # ステージを更新してmaster_leads.csvに保存
    if updated_recipients and not simulation:
        try:
            repo = ProductionCSVRepository(recipients_file=csv_path)
            repo.save_recipients(updated_recipients)
            print(f"✓ master_leads.csvを更新しました: {len(updated_recipients)}件")
        except Exception as e:
            print(f"✗ master_leads.csvの更新に失敗: {e}")
    elif updated_recipients and simulation:
        print(f"[SIMULATION] master_leads.csvは更新されません（シミュレーションモード）")
    
    print(f"\n=== 送信完了 ===")
    print(f"成功: {success_count}件")
    print(f"失敗: {fail_count}件")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="master_leads.csvの指定行にメールを送信")
    parser.add_argument(
        "--csv",
        type=str,
        default="/opt/libertycall/corp_collector/data/output/master_leads.csv",
        help="master_leads.csvのパス"
    )
    parser.add_argument(
        "--start",
        type=int,
        default=2,
        help="開始行（1ベース、ヘッダー含む）"
    )
    parser.add_argument(
        "--end",
        type=int,
        default=3,
        help="終了行（1ベース、ヘッダー含む）"
    )
    parser.add_argument(
        "--simulation",
        "-s",
        action="store_true",
        help="シミュレーションモード（実際には送信しない）"
    )
    
    args = parser.parse_args()
    
    send_emails_from_master_leads(
        csv_path=args.csv,
        start_line=args.start,
        end_line=args.end,
        simulation=args.simulation
    )

