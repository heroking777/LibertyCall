#!/usr/bin/env python3
"""Step1: gBizINFO企業名 → SearXNG検索 → ドメイン収集"""
import os
import sys
import time
import requests
from urllib.parse import urlparse
from datetime import datetime

INPUT_CSV = '/opt/libertycall/scraper/data/test_step1_input.csv'
OUTPUT_TSV = '/opt/libertycall/scraper/data/domains_found_test.tsv'
DONE_FILE = '/opt/libertycall/scraper/data/step1_done_test.txt'
SEARXNG_URL = 'http://localhost:8888/search'

SKIP_DOMAINS = [
    'wikipedia.org', 'facebook.com', 'twitter.com', 'linkedin.com',
    'instagram.com', 'youtube.com', 'tiktok.com', 'note.com',
    'wantedly.com', 'green-japan.com', 'en-japan.com', 'rikunabi.com',
    'mynavi.jp', 'type.jp', 'bizreach.jp', 'indeed.com',
    'openwork.jp', 'en-hyouban.com', 'prtimes.jp', 'baseconnect.in',
    'houjin-bangou.nta.go.jp', 'gbiz.go.jp', 'yahoo.co.jp',
    'google.com', 'amazon.co.jp', 'rakuten.co.jp', 'tabelog.com',
    'gnavi.co.jp', 'hotpepper.jp', 'suumo.jp', 'homes.co.jp'
]

def load_done():
    done = set()
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE, 'r') as f:
            for line in f:
                done.add(line.strip())
    return done

def search_domain(company_name):
    try:
        r = requests.get(SEARXNG_URL, params={
            'q': f'{company_name} 公式サイト',
            'format': 'json'
        }, timeout=15)
        results = r.json().get('results', [])
        for result in results[:3]:
            url = result.get('url', '')
            domain = urlparse(url).netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            if domain and not any(s in domain for s in SKIP_DOMAINS):
                return url, domain
        return None, None
    except:
        return None, None

def main():
    done = load_done()
    print(f"処理済み: {len(done)}社")
    
    outf = open(OUTPUT_TSV, 'a')
    donef = open(DONE_FILE, 'a')
    
    processed = 0
    found = 0
    
    with open(INPUT_CSV, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split(',', 1)
            if len(parts) < 2: continue
            corp_id, company_name = parts[0], parts[1]
            
            if corp_id in done: continue
            processed += 1
            
            url, domain = search_domain(company_name)
            if domain:
                found += 1
                outf.write(f"{corp_id}\t{company_name}\t{domain}\t{url}\n")
                outf.flush()
            
            donef.write(corp_id + '\n')
            donef.flush()
            
            if processed % 100 == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {processed}社 | ドメイン発見: {found} ({found/processed*100:.1f}%)")
            
            time.sleep(3)
    
    print(f"\n完了: {processed}社 | ドメイン発見: {found} ({found/processed*100:.1f}%)")
    outf.close()
    donef.close()

if __name__ == '__main__':
    main()
