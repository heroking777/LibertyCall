"""
マイナビ転職 入口スクリプト
求人一覧→詳細→リダイレクタ→公式サイトURL取得
メール抽出は後から共通エンジンで一括処理
"""
import csv
import os
import sys
import time
import random
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

OUTPUT_CSV = '/opt/libertycall/scraper/output/raw/mynavi_urls.csv'
FIELDNAMES = ['company_name', 'website', 'address', 'source_url', 'collected_at']

def ensure_csv():
    if not os.path.exists(OUTPUT_CSV):
        os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
        with open(OUTPUT_CSV, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

def load_existing():
    existing = set()
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, 'r') as f:
            for row in csv.DictReader(f):
                existing.add(row.get('website',''))
    return existing

def resolve_forwarder(url):
    if url.startswith('//'):
        url = 'https:' + url
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=False)
        return r.headers.get('Location', '')
    except:
        return ''

def get_job_links(page=1):
    url = f'https://tenshoku.mynavi.jp/list/?page={page}'
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, 'lxml')
    links = []
    for a in soup.select('a[href*="/jobinfo-"]'):
        href = a.get('href', '')
        if '/msg/' not in href and '/mimiyori/' not in href:
            full = 'https:' + href if href.startswith('//') else href
            if full not in links:
                links.append(full)
    return links

def get_detail(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'lxml')
    except:
        return None, None, None

    company = ''
    for tag in soup.select('[class*="company"]'):
        txt = tag.get_text(strip=True)
        if txt and len(txt) < 60:
            company = txt
            break

    hp = ''
    for a in soup.select('a[href*="url-forwarder"]'):
        hp = resolve_forwarder(a.get('href', ''))
        break

    address = ''
    for th in soup.select('th'):
        if '住所' in th.get_text(strip=True):
            td = th.find_next_sibling('td')
            if td:
                address = td.get_text(strip=True)[:80]
            break

    return company, hp, address

def append_row(row):
    with open(OUTPUT_CSV, 'a', newline='') as f:
        csv.DictWriter(f, fieldnames=FIELDNAMES).writerow(row)

def run(max_pages=100):
    ensure_csv()
    existing = load_existing()
    total_new = 0
    total_checked = 0

    for page in range(1, max_pages + 1):
        logger.info(f"Page {page}...")
        jobs = get_job_links(page)
        if not jobs:
            logger.info(f"No more jobs on page {page}")
            break

        for job_url in jobs:
            time.sleep(random.uniform(10, 30))
            company, hp, address = get_detail(job_url)
            total_checked += 1

            if not hp or not hp.startswith('http'):
                continue
            if hp in existing:
                continue

            existing.add(hp)
            append_row({
                'company_name': company,
                'website': hp,
                'address': address,
                'source_url': job_url,
                'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })
            total_new += 1
            logger.info(f"NEW: {company} -> {hp}")

        logger.info(f"Page {page} done. New: {total_new}, Checked: {total_checked}")

    logger.info(f"Finished. Total new URLs: {total_new}, Total checked: {total_checked}")

if __name__ == '__main__':
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    run(max_pages=pages)
