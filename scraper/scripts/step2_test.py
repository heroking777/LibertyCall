#!/usr/bin/env python3
"""Step2: ドメインリスト → SMTP推測 → メアド取得"""
import csv
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, '/opt/libertycall/scraper/engine')
from email_extractor import _guess_emails_smtp

INPUT_TSV = '/opt/libertycall/scraper/data/domains_found_test.tsv'
OUTPUT_CSV = '/opt/libertycall/scraper/output/searxng_emails_step2test.csv'
DONE_FILE = '/opt/libertycall/scraper/data/step2_done_test.txt'
CSV_FIELDS = ['email', 'company_name', 'address', 'phone', 'website', 'source', 'stage', 'last_sent_date', 'initial_sent_date', '除外']

def load_done():
    done = set()
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE, 'r') as f:
            for line in f:
                done.add(line.strip())
    return done

def main():
    done = load_done()
    print(f"処理済み: {len(done)}ドメイン")
    
    write_header = not os.path.exists(OUTPUT_CSV)
    outf = open(OUTPUT_CSV, 'a', newline='')
    writer = csv.DictWriter(outf, fieldnames=CSV_FIELDS)
    if write_header:
        writer.writeheader()
    
    donef = open(DONE_FILE, 'a')
    
    processed = 0
    found_emails = 0
    
    with open(INPUT_TSV, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split('\t')
            if len(parts) < 4: continue
            corp_id, company_name, domain, url = parts[0], parts[1], parts[2], parts[3]
            
            if corp_id in done: continue
            processed += 1
            
            emails = _guess_emails_smtp(url)
            for email in emails:
                found_emails += 1
                writer.writerow({
                    'email': email,
                    'company_name': company_name,
                    'address': '',
                    'phone': '',
                    'website': url,
                    'source': 'searxng_gbizinfo',
                    'stage': 'initial',
                    'last_sent_date': '',
                    'initial_sent_date': '',
                    '除外': ''
                })
            outf.flush()
            
            donef.write(corp_id + '\n')
            donef.flush()
            
            if processed % 50 == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {processed}社 | メアド: {found_emails}")
    
    print(f"\n完了: {processed}社 | メアド: {found_emails}")
    outf.close()
    donef.close()

if __name__ == '__main__':
    main()
