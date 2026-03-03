#!/usr/bin/env python3
"""
マイナビ転職 Step 2: メアド抽出
mynavi_urls.csv から公式サイトURLを読み込み、email_extractor.py でメアド抽出
"""
import csv
import os
import sys
import time
import random
import logging

sys.path.insert(0, '/opt/libertycall/scraper/engine')
from email_extractor import extract_emails

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

INPUT_CSV = '/opt/libertycall/scraper/output/raw/mynavi_urls.csv'
OUTPUT_CSV = '/opt/libertycall/scraper/output/raw/mynavi_emails.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'

CSV_FIELDS = ['email', 'company_name', 'address', 'phone', 'website', 'source', 'stage', 'last_sent_date', 'initial_sent_date', '除外']

def load_existing_emails():
    """既存メアドを読み込んで重複チェック用のセットを返す"""
    emails = set()
    for csv_path in [MASTER_CSV, OUTPUT_CSV]:
        if os.path.exists(csv_path):
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('email'):
                        emails.add(row['email'].lower())
    return emails

def append_to_csv(row):
    """CSVに1行追加（ヘッダーがなければ作成）"""
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def main():
    if not os.path.exists(INPUT_CSV):
        logger.error(f"Error: {INPUT_CSV} not found")
        return
    
    existing_emails = load_existing_emails()
    logger.info(f"Loaded {len(existing_emails)} existing emails for duplicate check")
    
    companies = []
    with open(INPUT_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('website'):
                companies.append(row)
    
    logger.info(f"Loaded {len(companies)} companies with website URLs")
    
    total_new = 0
    total_checked = 0
    
    for i, company in enumerate(companies, 1):
        website = company['website']
        company_name = company['company_name']
        address = company.get('address', '')
        
        logger.info(f"[{i}/{len(companies)}] {company_name} - {website}")
        
        time.sleep(random.uniform(3, 6))
        
        emails = extract_emails(website, deep_search=True)
        
        if not emails:
            logger.info(f"  No emails found")
            total_checked += 1
            continue
        
        for email in emails:
            if email.lower() not in existing_emails:
                row = {
                    'email': email,
                    'company_name': company_name,
                    'address': address,
                    'phone': '',
                    'website': website,
                    'source': 'mynavi',
                    'stage': 'initial',
                    'last_sent_date': '',
                    'initial_sent_date': '',
                    '除外': '',
                }
                append_to_csv(row)
                existing_emails.add(email.lower())
                total_new += 1
                logger.info(f"  ✓ NEW: {email}")
            else:
                logger.info(f"  - Skip (duplicate): {email}")
        
        total_checked += 1
        
        if i % 10 == 0:
            logger.info(f"\n--- Progress: {i}/{len(companies)} companies, {total_new} new emails ---\n")
    
    logger.info(f"\n✓ Finished. Total new emails: {total_new}, Total checked: {total_checked}")

if __name__ == '__main__':
    main()
