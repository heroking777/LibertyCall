#!/usr/bin/env python3
"""
Wantedly Step 2 TEST: Extract emails from first 10 companies
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

INPUT_FILE = '/tmp/wantedly_test_10.jsonl'
OUTPUT_CSV = '/tmp/wantedly_test_emails.csv'

CSV_FIELDS = ['email', 'company_name', 'address', 'phone', 'website', 'source', 'stage', 'last_sent_date', 'initial_sent_date', '除外']

def append_to_csv(row):
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def main():
    if os.path.exists(OUTPUT_CSV):
        os.remove(OUTPUT_CSV)
    
    companies = []
    with open(INPUT_FILE, 'r') as f:
        for line in f:
            company = json.loads(line)
            if company.get('url'):
                companies.append(company)
    
    print(f"Testing with {len(companies)} companies\n")
    
    total_new = 0
    
    for i, company in enumerate(companies, 1):
        website = company['url']
        company_name = company['name']
        address = company.get('address', '')
        wantedly_url = f"https://www.wantedly.com/companies/{company['id']}"
        
        print(f"[{i}/{len(companies)}] {company_name}")
        print(f"  Website: {website}")
        
        time.sleep(random.uniform(2, 4))
        
        emails = extract_emails(website, deep_search=True)
        
        if not emails:
            print(f"  ✗ No emails found\n")
            continue
        
        for email in emails:
            row = {
                'email': email,
                'company_name': company_name,
                'address': address,
                'phone': '',
                'website': website,
                'source': f'wantedly|{wantedly_url}',
                'stage': 'initial',
                'last_sent_date': '',
                'initial_sent_date': '',
                '除外': '',
            }
            append_to_csv(row)
            total_new += 1
            print(f"  ✓ {email}")
        
        print()
    
    print(f"\n{'='*60}")
    print(f"TEST COMPLETE: {total_new} emails extracted from {len(companies)} companies")
    print(f"Output: {OUTPUT_CSV}")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
