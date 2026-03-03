#!/usr/bin/env python3
"""
gBizINFO企業名 → SearXNG検索 → ドメイン取得 → SMTP推測 → メアド取得
"""
import csv
import json
import os
import sys
import time
import random
import requests
from urllib.parse import urlparse
from datetime import datetime

sys.path.insert(0, '/opt/libertycall/scraper/engine')
from email_extractor import _guess_emails_smtp

INPUT_CSV = '/opt/libertycall/scraper/data/gbizinfo_companies.csv'
OUTPUT_CSV = '/opt/libertycall/scraper/output/searxng_emails.csv'
DONE_FILE = '/opt/libertycall/scraper/data/searxng_done.txt'
SEARXNG_URL = 'http://localhost:8888/search'
CSV_FIELDS = ['email', 'company_name', 'address', 'phone', 'website', 'source', 'stage', 'last_sent_date', 'initial_sent_date', '除外']

# 処理済み企業を読み込み
def load_done():
    done = set()
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE, 'r') as f:
            for line in f:
                done.add(line.strip())
    return done

def search_domain(company_name):
    """SearXNGで企業名を検索し、公式ドメインを返す"""
    try:
        r = requests.get(SEARXNG_URL, params={
            'q': f'{company_name} 公式サイト',
            'format': 'json'
        }, timeout=15)
        results = r.json().get('results', [])
        if not results:
            return None, None
        
        # 上位3件から公式っぽいURLを選択
        for result in results[:3]:
            url = result.get('url', '')
            domain = urlparse(url).netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            # ポータルサイトを除外
            skip = ['wikipedia.org', 'facebook.com', 'twitter.com', 'linkedin.com',
                    'instagram.com', 'youtube.com', 'tiktok.com', 'note.com',
                    'wantedly.com', 'green-japan.com', 'en-japan.com', 'rikunabi.com',
                    'mynavi.jp', 'type.jp', 'bizreach.jp', 'indeed.com',
                    'openwork.jp', 'en-hyouban.com', 'prtimes.jp', 'baseconnect.in',
                    'houjin-bangou.nta.go.jp', 'gbiz.go.jp', 'yahoo.co.jp',
                    'google.com', 'amazon.co.jp', 'rakuten.co.jp']
            if not any(s in domain for s in skip):
                return url, domain
        return None, None
    except Exception as e:
        return None, None

def main():
    done = load_done()
    print(f"処理済み: {len(done)}社")
    
    # 出力CSVの準備
    write_header = not os.path.exists(OUTPUT_CSV)
    outf = open(OUTPUT_CSV, 'a', newline='')
    writer = csv.DictWriter(outf, fieldnames=CSV_FIELDS)
    if write_header:
        writer.writeheader()
    
    donef = open(DONE_FILE, 'a')
    
    processed = 0
    found_domains = 0
    found_emails = 0
    
    with open(INPUT_CSV, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',', 1)
            if len(parts) < 2:
                continue
            corp_id, company_name = parts[0], parts[1]
            
            if corp_id in done:
                continue
            
            processed += 1
            
            # SearXNG検索
            url, domain = search_domain(company_name)
            
            if domain:
                found_domains += 1
                # SMTP推測
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
            
            # 処理済みに追加
            donef.write(corp_id + '\n')
            donef.flush()
            
            # 進捗表示（100件ごと）
            if processed % 100 == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {processed}社処理 | ドメイン: {found_domains} | メアド: {found_emails}")
            
            # レート制限（5秒間隔）
            time.sleep(5)
    
    print(f"\n完了: {processed}社処理 | ドメイン: {found_domains} | メアド: {found_emails}")
    outf.close()
    donef.close()

if __name__ == '__main__':
    main()
