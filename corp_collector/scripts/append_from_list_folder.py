#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
listフォルダ内の全CSVファイルを読み込んで本リスト（master_leads.csv）に追記するスクリプト

使用方法:
    python scripts/append_from_list_folder.py [listフォルダのパス]
"""

import csv
import sys
import argparse
from pathlib import Path
from typing import Set, List, Dict
import re

# 本リストファイルのパス
MASTER_FILE = Path("data/output/master_leads.csv")
LIST_FOLDER = Path("/opt/libertycall/list")


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
                    # メールアドレスの正規化（小文字化、前後の空白削除）
                    email = email.lower().strip()
                    # mailto:プレフィックスを削除
                    email = re.sub(r'^mailto:', '', email, flags=re.IGNORECASE)
                    if email:
                        emails.add(email)
        print(f"本リストから {len(emails)} 件のメールアドレスを読み込みました")
    except Exception as e:
        print(f"本リストの読み込みエラー: {e}")
        sys.exit(1)
    
    return emails


def normalize_email(email: str) -> str:
    """メールアドレスを正規化"""
    if not email:
        return ""
    email = email.strip().lower()
    # mailto:プレフィックスを削除
    email = re.sub(r'^mailto:', '', email, flags=re.IGNORECASE)
    return email


def load_csv_file(csv_file: Path) -> List[Dict[str, str]]:
    """CSVファイルからレコードを読み込む（複数のフォーマットに対応）"""
    records = []
    if not csv_file.exists():
        print(f"ファイルが見つかりません: {csv_file}")
        return records
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            # まず1行目を読んでカラム名を確認
            first_line = f.readline()
            f.seek(0)
            
            reader = csv.DictReader(f)
            for row in reader:
                # 複数のフォーマットに対応
                email = ""
                company_name = ""
                
                # E-Mailカラムを探す（大文字小文字、空白を考慮）
                for key in row.keys():
                    if 'mail' in key.lower() or 'e-mail' in key.lower() or 'email' in key.lower():
                        email = row.get(key, '').strip()
                        break
                
                # 会社名カラムを探す
                for key in row.keys():
                    if '氏名' in key or 'company' in key.lower() or 'name' in key.lower():
                        company_name = row.get(key, '').strip()
                        break
                
                # メールアドレスがなければスキップ
                email = normalize_email(email)
                if not email:
                    continue
                
                # 会社名がなければメールアドレスから推測
                if not company_name:
                    # メールアドレスの@より前の部分を会社名として使用（最後の手段）
                    company_name = email.split('@')[0] if '@' in email else ""
                
                records.append({
                    'email': email,
                    'company_name': company_name,
                    'address': '',
                    'stage': 'initial'
                })
        
        print(f"  {csv_file.name}: {len(records)} 件のレコードを読み込みました")
    except Exception as e:
        print(f"  {csv_file.name}: 読み込みエラー: {e}")
        return []
    
    return records


def find_csv_files(list_folder: Path) -> List[Path]:
    """listフォルダ内の全CSVファイルを検索（__MACOSXと._で始まるファイルを除外）"""
    csv_files = []
    if not list_folder.exists():
        print(f"フォルダが見つかりません: {list_folder}")
        return csv_files
    
    for csv_file in list_folder.rglob("*.csv"):
        # __MACOSXフォルダと._で始まるファイルを除外
        if "__MACOSX" in str(csv_file) or csv_file.name.startswith("._"):
            continue
        csv_files.append(csv_file)
    
    return sorted(csv_files)


def filter_new_records(
    records: List[Dict[str, str]],
    existing_emails: Set[str]
) -> List[Dict[str, str]]:
    """既存のメールアドレスと重複しないレコードのみを返す"""
    new_records = []
    duplicate_count = 0
    
    for record in records:
        email = normalize_email(record.get('email', ''))
        if not email:
            continue
        
        if email in existing_emails:
            duplicate_count += 1
            continue
        
        new_records.append(record)
        existing_emails.add(email)  # 同じファイル内の重複も防ぐ
    
    if duplicate_count > 0:
        print(f"  重複除外: {duplicate_count} 件")
    
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
        fieldnames = ['email', 'company_name', 'address', 'stage']
        if master_file.exists():
            with open(master_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
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
        description='listフォルダ内の全CSVファイルを本リストに追記する'
    )
    parser.add_argument(
        'list_folder',
        nargs='?',
        default=str(LIST_FOLDER),
        help=f'listフォルダのパス（デフォルト: {LIST_FOLDER}）'
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
    list_folder = Path(args.list_folder)
    
    print(f"本リスト: {master_file}")
    print(f"listフォルダ: {list_folder}")
    print("-" * 50)
    
    # 本リストから既存のメールアドレスを読み込む
    existing_emails = load_master_emails(master_file)
    
    # listフォルダ内の全CSVファイルを検索
    csv_files = find_csv_files(list_folder)
    print(f"\n{len(csv_files)} 個のCSVファイルが見つかりました")
    
    if not csv_files:
        print("処理するCSVファイルがありません")
        return
    
    # 全ファイルからレコードを読み込む
    all_records = []
    for csv_file in csv_files:
        records = load_csv_file(csv_file)
        all_records.extend(records)
    
    print(f"\n合計 {len(all_records)} 件のレコードを読み込みました")
    
    if not all_records:
        print("新しいレコードがありません")
        return
    
    # 重複を除外
    print("\n重複チェック中...")
    unique_records = filter_new_records(all_records, existing_emails)
    
    print(f"\n重複除外後: {len(unique_records)} 件の新規レコード")
    
    if not unique_records:
        print("追記する新しいレコードがありません（すべて重複）")
        return
    
    # 本リストに追記
    print("\n本リストに追記中...")
    append_to_master(master_file, unique_records)
    
    # 実際のファイルから最終件数を確認
    final_count = 0
    if master_file.exists():
        with open(master_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            final_count = sum(1 for row in reader if row.get('email', '').strip())
    
    print("-" * 50)
    print("処理が完了しました")
    print(f"本リストの総件数: {final_count} 件")
    print(f"  (元々: {len(existing_emails)} 件 + 追加: {len(unique_records)} 件)")


if __name__ == "__main__":
    main()

