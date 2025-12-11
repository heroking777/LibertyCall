#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本リスト（master_leads.csv）に新しいデータを追記するスクリプト

使用方法:
    python scripts/append_to_master.py [新しいCSVファイルのパス]
    
    または、日付を指定:
    python scripts/append_to_master.py --date 20251205
"""

import csv
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Set, List, Dict

# 本リストファイルのパス
MASTER_FILE = Path("data/output/master_leads.csv")
OUTPUT_DIR = Path("data/output")


def load_master_emails(master_file: Path) -> Set[str]:
    """本リストから既存のメールアドレスのセットを取得"""
    emails = set()
    if not master_file.exists():
        print(f"本リストファイルが見つかりません: {master_file}")
        return emails
    
    try:
        with open(master_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get('email', '').strip()
                if email:
                    emails.add(email.lower())  # 大文字小文字を区別しない
        print(f"本リストから {len(emails)} 件のメールアドレスを読み込みました")
    except Exception as e:
        print(f"本リストの読み込みエラー: {e}")
        sys.exit(1)
    
    return emails


def load_new_records(new_file: Path) -> List[Dict[str, str]]:
    """新しいCSVファイルからレコードを読み込む"""
    records = []
    if not new_file.exists():
        print(f"新しいファイルが見つかりません: {new_file}")
        return records
    
    try:
        with open(new_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append({
                    'email': row.get('email', '').strip(),
                    'company_name': row.get('company_name', '').strip(),
                    'address': row.get('address', '').strip(),
                    'stage': row.get('stage', 'initial').strip()  # stage列がなければinitial
                })
        print(f"新しいファイルから {len(records)} 件のレコードを読み込みました")
    except Exception as e:
        print(f"新しいファイルの読み込みエラー: {e}")
        sys.exit(1)
    
    return records


def filter_new_records(
    records: List[Dict[str, str]],
    existing_emails: Set[str]
) -> List[Dict[str, str]]:
    """既存のメールアドレスと重複しないレコードのみを返す"""
    new_records = []
    for record in records:
        email = record.get('email', '').strip().lower()
        if email and email not in existing_emails:
            new_records.append(record)
            existing_emails.add(email)  # 同じファイル内の重複も防ぐ
    
    return new_records


def append_to_master(
    master_file: Path,
    new_records: List[Dict[str, str]]
) -> None:
    """本リストに新しいレコードを追記"""
    if not new_records:
        print("追記する新しいレコードがありません")
        return
    
    try:
        # マスターファイルのフィールド名を確認
        with open(master_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
        
        # 追記モードで開く
        with open(master_file, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            # フィールド名に合わせてレコードを整形
            formatted_records = []
            for record in new_records:
                formatted_record = {}
                for field in fieldnames:
                    formatted_record[field] = record.get(field, 'initial' if field == 'stage' else '')
                formatted_records.append(formatted_record)
            writer.writerows(formatted_records)
        
        print(f"本リストに {len(new_records)} 件のレコードを追記しました")
    except Exception as e:
        print(f"本リストへの追記エラー: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='本リストに新しいデータを追記する'
    )
    parser.add_argument(
        'file',
        nargs='?',
        help='追記するCSVファイルのパス'
    )
    parser.add_argument(
        '--date',
        help='日付を指定（YYYYMMDD形式）。例: 20251205'
    )
    parser.add_argument(
        '--master',
        default=str(MASTER_FILE),
        help=f'本リストファイルのパス（デフォルト: {MASTER_FILE}）'
    )
    
    args = parser.parse_args()
    
    # 作業ディレクトリをcorp_collectorに変更
    script_dir = Path(__file__).parent
    corp_collector_dir = script_dir.parent
    import os
    os.chdir(corp_collector_dir)
    
    master_file = Path(args.master)
    
    # 新しいファイルのパスを決定
    if args.date:
        new_file = OUTPUT_DIR / f"leads_{args.date}.csv"
    elif args.file:
        new_file = Path(args.file)
    else:
        # 今日の日付のファイルを自動検出
        today = datetime.now().strftime("%Y%m%d")
        new_file = OUTPUT_DIR / f"leads_{today}.csv"
        if not new_file.exists():
            print(f"エラー: 新しいファイルが見つかりません: {new_file}")
            print("使用方法: python scripts/append_to_master.py [ファイルパス] または --date [YYYYMMDD]")
            sys.exit(1)
    
    print(f"本リスト: {master_file}")
    print(f"新しいファイル: {new_file}")
    print("-" * 50)
    
    # 本リストから既存のメールアドレスを読み込む
    existing_emails = load_master_emails(master_file)
    
    # 新しいファイルからレコードを読み込む
    new_records = load_new_records(new_file)
    
    if not new_records:
        print("新しいレコードがありません")
        return
    
    # 重複を除外
    unique_records = filter_new_records(new_records, existing_emails)
    
    print(f"重複除外後: {len(unique_records)} 件の新規レコード")
    
    if not unique_records:
        print("追記する新しいレコードがありません（すべて重複）")
        return
    
    # 本リストに追記
    append_to_master(master_file, unique_records)
    
    print("-" * 50)
    print("処理が完了しました")


if __name__ == "__main__":
    main()

