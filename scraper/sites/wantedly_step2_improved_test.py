#!/usr/bin/env python3
"""
Wantedly Step 2 改良版テスト
改良版email_extractor (deep_search=True, smtp_guess=True) で651社を再処理
旧結果(22件)との比較を実施
"""
import csv
import json
import sys
import time
import random
import os
from pathlib import Path

sys.path.insert(0, '/opt/libertycall/scraper/engine')
from email_extractor import extract_emails

INPUT_FILE = '/opt/libertycall/scraper/output/wantedly_companies_raw.jsonl'
OUTPUT_CSV = '/opt/libertycall/scraper/output/wantedly_emails_improved.csv'
OLD_OUTPUT_CSV = '/opt/libertycall/scraper/output/wantedly_emails.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'

CSV_FIELDS = ['email', 'company_name', 'address', 'phone', 'website', 'source', 'stage', 'last_sent_date', 'initial_sent_date', '除外']

def load_existing_emails():
    """既存メアドを読み込んで重複チェック用のセットを返す"""
    emails = set()
    for csv_path in [MASTER_CSV, OUTPUT_CSV, OLD_OUTPUT_CSV]:
        if os.path.exists(csv_path):
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('email'):
                        emails.add(row['email'].lower())
    return emails

def load_old_results():
    """旧結果を読み込み"""
    old_emails = {}
    if os.path.exists(OLD_OUTPUT_CSV):
        with open(OLD_OUTPUT_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('email') and row.get('website'):
                    old_emails[row['website']] = row['email']
    return old_emails

def append_to_csv(row):
    """CSVに1行追加（ヘッダーがなければ作成）"""
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def main():
    print("="*70)
    print("Wantedly Step 2 改良版テスト")
    print("改良A: 2階層クロール + 拡張優先パス")
    print("改良B: SMTP検証")
    print("="*70)
    
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found. Run step1 first.")
        return
    
    existing_emails = load_existing_emails()
    old_results = load_old_results()
    
    print(f"\n既存メアド総数: {len(existing_emails)}件")
    print(f"旧結果(wantedly_emails.csv): {len(old_results)}件\n")
    
    companies = []
    with open(INPUT_FILE, 'r') as f:
        for line in f:
            company = json.loads(line)
            if company.get('url'):
                companies.append(company)
    
    print(f"処理対象企業数: {len(companies)}社\n")
    print("="*70)
    
    total_new = 0
    total_checked = 0
    total_improved = 0  # 旧版で取れなかったが改良版で取れた数
    total_old_found = 0  # 旧版でも取れていた数
    
    for i, company in enumerate(companies, 1):
        website = company['url']
        company_name = company['name']
        address = company.get('address', '')
        
        print(f"\n[{i}/{len(companies)}] {company_name}")
        print(f"  URL: {website}")
        
        # 改良版email_extractorで抽出
        # deep_search=True: 2階層クロール有効
        # smtp_guess=True: SMTP検証有効
        time.sleep(random.uniform(3, 6))
        
        emails = extract_emails(website, deep_search=True, smtp_guess=True)
        
        if not emails:
            print(f"  ❌ メアド未発見")
            total_checked += 1
            continue
        
        # 旧結果との比較
        was_in_old = website in old_results
        
        for email in emails:
            if email.lower() not in existing_emails:
                row = {
                    'email': email,
                    'company_name': company_name,
                    'address': address,
                    'phone': '',
                    'website': website,
                    'source': 'wantedly_improved',
                    'stage': 'initial',
                    'last_sent_date': '',
                    'initial_sent_date': '',
                    '除外': '',
                }
                append_to_csv(row)
                existing_emails.add(email.lower())
                total_new += 1
                
                if was_in_old:
                    print(f"  ✓ NEW (旧版でも取得済み): {email}")
                    total_old_found += 1
                else:
                    print(f"  ✓✓ NEW (改良版で新規取得): {email}")
                    total_improved += 1
            else:
                print(f"  - Skip (duplicate): {email}")
        
        total_checked += 1
        
        if i % 50 == 0:
            print(f"\n{'='*70}")
            print(f"進捗: {i}/{len(companies)} 企業処理完了")
            print(f"新規取得: {total_new}件 (改良版のみ: {total_improved}件, 旧版でも取得: {total_old_found}件)")
            print(f"{'='*70}")
    
    # 最終レポート
    print("\n\n" + "="*70)
    print("テスト完了 - 最終レポート")
    print("="*70)
    
    print(f"\n処理企業数: {total_checked}/{len(companies)}社")
    print(f"\n【結果比較】")
    print(f"  旧版 (wantedly_emails.csv): {len(old_results)}件")
    print(f"  改良版 新規取得: {total_new}件")
    print(f"    - 改良版のみで取得: {total_improved}件")
    print(f"    - 旧版でも取得済み: {total_old_found}件")
    
    if total_improved > 0:
        improvement_rate = (total_improved / len(companies)) * 100
        print(f"\n【改善効果】")
        print(f"  改良版での追加取得率: {improvement_rate:.2f}%")
        print(f"  旧版打率: {len(old_results)/len(companies)*100:.2f}%")
        print(f"  改良版打率: {(len(old_results)+total_improved)/len(companies)*100:.2f}%")
        print(f"  改善幅: +{total_improved}件 (+{improvement_rate:.2f}ポイント)")
    
    print(f"\n出力ファイル: {OUTPUT_CSV}")
    print("="*70)

if __name__ == '__main__':
    main()
