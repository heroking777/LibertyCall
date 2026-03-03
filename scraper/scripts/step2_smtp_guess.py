#!/usr/bin/env python3
"""Step2: ドメインリスト → SMTP推測 → メアド取得（並列対応・7列版）"""
import csv
import os
import sys
import time
import fcntl
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, '/opt/libertycall/scraper/engine')
from email_extractor import extract_emails

INPUT_TSV = '/opt/libertycall/scraper/data/domains_found.tsv'
OUTPUT_CSV = '/opt/libertycall/scraper/output/searxng_emails.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'

WORKER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
TOTAL_WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 1

def load_existing_domains():
    domains = set()
    for csv_path in [MASTER_CSV, OUTPUT_CSV]:
        if os.path.exists(csv_path):
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and '@' in row[0]:
                        domains.add(row[0].split('@')[1].lower())
    return domains

def write_csv_locked(filepath, line):
    with open(filepath, 'a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def main():
    existing_domains = load_existing_domains()
    print(f"Worker {WORKER_ID}/{TOTAL_WORKERS} 起動")
    print(f"既存ドメイン: {len(existing_domains)}件")

    processed = 0
    skipped = 0
    found_emails = 0
    line_num = 0

    with open(INPUT_TSV, 'r') as f:
        for line in f:
            if line_num % TOTAL_WORKERS != WORKER_ID:
                line_num += 1
                continue
            line_num += 1

            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            corp_id, company_name, domain, url = parts[0], parts[1], parts[2], parts[3]

            if domain.lower() in existing_domains:
                skipped += 1
                continue

            emails = extract_emails(url, deep_search=True, smtp_guess=True)
            if emails:
                email = emails[0]
                found_emails += 1
                existing_domains.add(domain.lower())
                # master_leads.csvと同じ7列: email,company_name,address,stage,last_sent_date,initial_sent_date,除外
                write_csv_locked(OUTPUT_CSV, f"{email},{company_name},,initial,,,\n")

            processed += 1
            if processed % 50 == 0:
                print(f"[W{WORKER_ID}] {datetime.now().strftime('%H:%M:%S')} 処理:{processed} | スキップ:{skipped} | メアド:{found_emails}")

    print(f"[W{WORKER_ID}] 完了: 処理:{processed} | スキップ:{skipped} | メアド:{found_emails}")

if __name__ == '__main__':
    main()
