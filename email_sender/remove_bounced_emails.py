#!/usr/bin/env python3
"""
バウンスしたメールアドレスをmaster_leads.csvから手動削除するスクリプト

使用方法:
    python3 email_sender/remove_bounced_emails.py [--dry-run]

オプション:
    --dry-run: 実際には削除せず、削除対象を表示するだけ
"""

import csv
import sys
import argparse
from pathlib import Path
from typing import Set

# プロジェクトルートのパス
PROJECT_ROOT = Path(__file__).parent.parent
EVENTS_LOG_PATH = PROJECT_ROOT / "logs" / "sendgrid_events.csv"
MASTER_LEADS_PATH = Path(__file__).parent / "data" / "master_leads.csv"
BACKUP_PATH = Path(__file__).parent / "data" / "master_leads.csv.backup"


def load_bounced_emails() -> Set[str]:
    """
    SendGridイベントログからバウンスしたメールアドレスを取得
    
    Returns:
        バウンスしたメールアドレスのセット（小文字）
    """
    bounced = set()
    
    if not EVENTS_LOG_PATH.exists():
        print(f"[WARN] イベントログファイルが見つかりません: {EVENTS_LOG_PATH}")
        return bounced
    
    try:
        with open(EVENTS_LOG_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # ヘッダーをスキップ
            
            for row in reader:
                if len(row) >= 2:
                    email = row[0].strip().lower()
                    event = row[1].strip().lower()
                    
                    # bounce, dropped, spamreport, auto_reply を検出
                    if event in ["bounce", "dropped", "spamreport", "auto_reply"]:
                        if email:
                            bounced.add(email)
    
    except Exception as e:
        print(f"[ERROR] イベントログの読み込みエラー: {e}")
        return bounced
    
    return bounced


def remove_bounced_from_master_leads(dry_run: bool = False) -> int:
    """
    master_leads.csvからバウンスしたメールアドレスを削除
    
    Args:
        dry_run: Trueの場合、実際には削除せず表示するだけ
    
    Returns:
        削除した件数
    """
    if not MASTER_LEADS_PATH.exists():
        print(f"[ERROR] master_leads.csvが見つかりません: {MASTER_LEADS_PATH}")
        return 0
    
    # バウンスしたメールアドレスを取得
    bounced_emails = load_bounced_emails()
    
    if not bounced_emails:
        print("[INFO] バウンスしたメールアドレスは見つかりませんでした。")
        return 0
    
    print(f"[INFO] 検出されたバウンス/無効メール: {len(bounced_emails)} 件")
    
    # master_leads.csvを読み込む
    rows = []
    removed_count = 0
    
    try:
        with open(MASTER_LEADS_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            
            if not fieldnames:
                print("[ERROR] CSVファイルのヘッダーが見つかりません")
                return 0
            
            for row in reader:
                email = row.get("email", "").strip().lower()
                
                if email in bounced_emails:
                    removed_count += 1
                    if dry_run:
                        print(f"[DRY-RUN] 削除対象: {row.get('email', '')} ({row.get('company_name', '')})")
                    # 削除対象なのでスキップ
                    continue
                
                rows.append(row)
        
        print(f"[INFO] 削除対象: {removed_count} 件")
        print(f"[INFO] 残り件数: {len(rows)} 件")
        
        if dry_run:
            print("[DRY-RUN] 実際の削除は行いませんでした。")
            return removed_count
        
        # バックアップを作成
        import shutil
        shutil.copy2(MASTER_LEADS_PATH, BACKUP_PATH)
        print(f"[INFO] バックアップを作成しました: {BACKUP_PATH}")
        
        # クリーンなリストを保存
        with open(MASTER_LEADS_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        print(f"[INFO] master_leads.csvを更新しました。{removed_count} 件のメールアドレスを削除しました。")
        return removed_count
    
    except Exception as e:
        print(f"[ERROR] 処理エラー: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description="バウンスしたメールアドレスをmaster_leads.csvから削除"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には削除せず、削除対象を表示するだけ"
    )
    
    args = parser.parse_args()
    
    print("=== バウンスメールアドレス削除ツール ===")
    print(f"イベントログ: {EVENTS_LOG_PATH}")
    print(f"対象ファイル: {MASTER_LEADS_PATH}")
    print()
    
    if args.dry_run:
        print("[DRY-RUN モード] 実際の削除は行いません。")
        print()
    
    removed_count = remove_bounced_from_master_leads(dry_run=args.dry_run)
    
    if removed_count > 0:
        print()
        print(f"✅ 処理完了: {removed_count} 件のメールアドレスを削除しました。")
    else:
        print()
        print("✅ 処理完了: 削除対象はありませんでした。")
    
    return 0 if removed_count >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())

