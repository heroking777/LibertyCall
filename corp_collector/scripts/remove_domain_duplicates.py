#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マスターリストからドメイン重複を削除するスクリプト
1ドメイン1メールアドレスのみを保持

使用方法:
    python scripts/remove_domain_duplicates.py [--dry-run]
"""

import csv
import sys
import argparse
import shutil
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# マスターリストファイルのパス
MASTER_FILE = Path("data/output/master_leads.csv")
BACKUP_DIR = Path("data/output/backup")


def get_email_priority(email: str) -> int:
    """
    メールアドレスの優先順位を返す
    数値が小さいほど優先度が高い
    
    Args:
        email: メールアドレス
        
    Returns:
        優先順位（0が最高）
    """
    email_lower = email.lower()
    
    # 優先度の高いメールアドレス
    priority_emails = [
        'info@',
        'contact@',
        'support@',
        'sales@',
        'inquiry@',
        'inquiries@',
        'mail@',
        'office@',
        'general@',
    ]
    
    for i, priority in enumerate(priority_emails):
        if email_lower.startswith(priority):
            return i
    
    # その他は低優先度
    return 999


def remove_domain_duplicates(dry_run: bool = False) -> None:
    """
    マスターリストからドメイン重複を削除
    
    Args:
        dry_run: Trueの場合、実際には削除せずに結果のみ表示
    """
    if not MASTER_FILE.exists():
        print(f"エラー: マスターリストファイルが見つかりません: {MASTER_FILE}")
        sys.exit(1)
    
    # ドメインごとのレコードを集計
    domain_to_records = defaultdict(list)
    all_records = []
    
    print(f"マスターリストを読み込み中: {MASTER_FILE}")
    
    with open(MASTER_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        if not fieldnames:
            print("エラー: CSVファイルのヘッダーが見つかりません")
            sys.exit(1)
        
        for row in reader:
            email = row.get('email', '').strip()
            if email and '@' in email:
                domain = email.split('@')[-1].lower()
                domain_to_records[domain].append(row)
            all_records.append(row)
    
    print(f"総件数: {len(all_records)} 件")
    print(f"ユニークなドメイン数: {len(domain_to_records)} 件")
    
    # 重複ドメインを確認
    duplicate_domains = {d: records for d, records in domain_to_records.items() if len(records) > 1}
    
    if not duplicate_domains:
        print("ドメイン重複はありませんでした。")
        return
    
    print(f"重複ドメイン数: {len(duplicate_domains)} 件")
    print(f"削除予定件数: {sum(len(records) - 1 for records in duplicate_domains.values())} 件")
    
    # 各ドメインから1件のみを選択（優先順位に基づく）
    selected_records = []
    removed_count = 0
    
    for domain, records in domain_to_records.items():
        if len(records) == 1:
            # 重複なし
            selected_records.append(records[0])
        else:
            # 重複あり：優先順位でソートして最初の1件を選択
            sorted_records = sorted(
                records,
                key=lambda r: (get_email_priority(r.get('email', '')), r.get('email', '').lower())
            )
            selected_records.append(sorted_records[0])
            removed_count += len(sorted_records) - 1
    
    print(f"\n削除後の件数: {len(selected_records)} 件")
    print(f"削除件数: {removed_count} 件")
    
    if dry_run:
        print("\n[DRY-RUN] 実際の削除は行いませんでした。")
        
        # 削除されるレコードの例を表示
        print("\n削除されるレコードの例（最初の5ドメイン）:")
        for i, (domain, records) in enumerate(list(duplicate_domains.items())[:5], 1):
            sorted_records = sorted(
                records,
                key=lambda r: (get_email_priority(r.get('email', '')), r.get('email', '').lower())
            )
            print(f"\n{i}. {domain} ({len(records)} 件 → 1件に削減):")
            print(f"   保持: {sorted_records[0].get('email', '')} / {sorted_records[0].get('company_name', '')[:40]}")
            for rec in sorted_records[1:]:
                print(f"   削除: {rec.get('email', '')} / {rec.get('company_name', '')[:40]}")
        return
    
    # バックアップを作成
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"master_leads_backup_{timestamp}.csv"
    shutil.copy2(MASTER_FILE, backup_file)
    print(f"\nバックアップを作成しました: {backup_file}")
    
    # マスターリストを更新
    print(f"マスターリストを更新中: {MASTER_FILE}")
    
    with open(MASTER_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected_records)
    
    print(f"✅ マスターリストを更新しました。{removed_count} 件のレコードを削除しました。")


def main():
    parser = argparse.ArgumentParser(
        description='マスターリストからドメイン重複を削除'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='実際には削除せずに結果のみ表示'
    )
    
    args = parser.parse_args()
    
    # 作業ディレクトリをcorp_collectorに変更
    script_dir = Path(__file__).parent
    corp_collector_dir = script_dir.parent
    import os
    os.chdir(corp_collector_dir)
    
    remove_domain_duplicates(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

