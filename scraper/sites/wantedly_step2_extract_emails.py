#!/usr/bin/env python3
"""
Wantedly Step 2: Extract emails from company websites
Reads wantedly_companies_raw.jsonl and uses email_extractor.py to get emails
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
OUTPUT_CSV = '/opt/libertycall/scraper/output/wantedly_emails.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'

CSV_FIELDS = ['email', 'company_name', 'address', 'phone', 'website', 'source', 'stage', 'last_sent_date', 'initial_sent_date', '除外']

def load_existing_emails():
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
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found. Run step1 first.")
        return
    
    existing_emails = load_existing_emails()
    
    companies = []
    with open(INPUT_FILE, 'r') as f:
        for line in f:
            company = json.loads(line)
            if company.get('url'):
                companies.append(company)
    
    print(f"Loaded {len(companies)} companies with website URLs")
    
    total_new = 0
    total_checked = 0
    
    for i, company in enumerate(companies, 1):
        website = company['url']
        company_name = company['name']
        address = company.get('address', '')
        
        print(f"[{i}/{len(companies)}] {company_name} - {website}")
        
        time.sleep(random.uniform(3, 6))
        
        emails = extract_emails(website, deep_search=True)
        
        if not emails:
            print(f"  No emails found")
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
                    'source': 'wantedly',
                    'stage': 'initial',
                    'last_sent_date': '',
                    'initial_sent_date': '',
                    '除外': '',
                }
                append_to_csv(row)
                existing_emails.add(email.lower())
                total_new += 1
                print(f"  ✓ NEW: {email}")
            else:
                print(f"  - Skip (duplicate): {email}")
        
        total_checked += 1
        
        if i % 50 == 0:
            print(f"\n--- Progress: {i}/{len(companies)} companies, {total_new} new emails ---\n")
    
    print(f"\n✓ Finished. Total new emails: {total_new}, Total checked: {total_checked}")

if __name__ == '__main__':
    main()
