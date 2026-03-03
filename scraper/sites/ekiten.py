"""
エキテン入口スクリプト
カテゴリ別に店舗一覧を巡回し、詳細ページからJSON-LDで企業情報を取得
公式サイトURLを共通エンジンに渡してメアド抽出
"""

import csv
import json
import os
import re
import sys
import time
import random
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# 共通エンジンのパスを追加
sys.path.insert(0, '/opt/libertycall/scraper/engine')
from email_extractor import extract_emails

def setup_logger(category='ekiten'):
    log_path = f'/opt/libertycall/scraper/logs/ekiten_{category}.log'
    logger = logging.getLogger(f'ekiten_{category}')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

CATEGORIES = {
    'clinic': 'https://www.ekiten.jp/clinic/',
    'life': 'https://www.ekiten.jp/life/',
    'professional': 'https://www.ekiten.jp/professional/',
    'relax': 'https://www.ekiten.jp/relax/',
    'food': 'https://www.ekiten.jp/food/',
    'beauty': 'https://www.ekiten.jp/beauty/',
    'school': 'https://www.ekiten.jp/school/',
    'lesson': 'https://www.ekiten.jp/lesson/',
    'store': 'https://www.ekiten.jp/store/',
}

MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'
OUTPUT_CSV = '/opt/libertycall/scraper/output/raw/ekiten.csv'
PROGRESS_FILE = '/opt/libertycall/scraper/logs/ekiten_progress.json'

CSV_FIELDS = ['email','company_name','address','phone','website','source','stage','last_sent_date','initial_sent_date','除外']


def load_existing_emails():
    emails = set()
    if os.path.exists(MASTER_CSV):
        with open(MASTER_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('email'):
                    emails.add(row['email'].lower())
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('email'):
                    emails.add(row['email'].lower())
    return emails


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


def get_shop_urls(category_url, page):
    url = f"{category_url}?page={page}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, 'lxml')
        shops = []
        seen = set()
        for a in soup.select('a[href*="/shop_"]'):
            href = a.get('href','')
            if href and href not in seen and '#' not in href:
                seen.add(href)
                if not href.startswith('http'):
                    href = 'https://www.ekiten.jp' + href
                shops.append(href)
        return shops
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return []


def get_shop_detail(shop_url):
    try:
        resp = requests.get(shop_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, 'lxml')
        
        info = {'company_name': '', 'address': '', 'phone': '', 'website': ''}
        
        # JSON-LD
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                info['company_name'] = data.get('name', '')
                info['phone'] = data.get('telephone', '')
                addr = data.get('address', {})
                if isinstance(addr, dict):
                    info['address'] = addr.get('addressRegion','') + addr.get('addressLocality','') + addr.get('streetAddress','')
            except:
                pass
        
        # 公式サイトURL
        for a in soup.select('a[href]'):
            href = a.get('href','')
            txt = a.get_text(strip=True)
            if 'ekiten' not in href and href.startswith('http'):
                if '公式' in txt or 'ホームページ' in txt or 'HP' in txt:
                    info['website'] = href
                    break
        
        # 公式が見つからなかった場合、外部リンクの最初を使う
        if not info['website']:
            for a in soup.select('a[href]'):
                href = a.get('href','')
                if href.startswith('http') and 'ekiten' not in href and 'google' not in href and 'facebook' not in href and 'twitter' not in href and 'designone' not in href and 'akala' not in href:
                    info['website'] = href
                    break
        
        return info
    except Exception as e:
        logger.error(f"Error fetching {shop_url}: {e}")
        return None


def append_to_csv(row):
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run(category_name='clinic', max_pages=5):
    global logger
    logger = setup_logger(category_name)
    if category_name not in CATEGORIES:
        logger.error(f"Unknown category: {category_name}")
        return
    
    category_url = CATEGORIES[category_name]
    existing = load_existing_emails()
    progress = load_progress()
    start_page = progress.get(category_name, 1)
    
    total_new = 0
    total_checked = 0
    
    logger.info(f"Starting {category_name} from page {start_page}")
    
    for page in range(start_page, start_page + max_pages):
        logger.info(f"Page {page}...")
        shop_urls = get_shop_urls(category_url, page)
        
        if not shop_urls:
            logger.info(f"No more shops on page {page}")
            break
        
        for shop_url in shop_urls:
            time.sleep(random.uniform(10, 30))
            total_checked += 1
            
            detail = get_shop_detail(shop_url)
            if not detail or not detail['website']:
                continue
            
            # 公式サイトからメアド抽出
            time.sleep(random.uniform(2, 5))
            emails = extract_emails(detail['website'])
            
            for email in emails:
                if email.lower() not in existing:
                    row = {
                        'email': email,
                        'company_name': detail['company_name'],
                        'address': detail['address'],
                        'phone': detail['phone'],
                        'website': detail['website'],
                        'source': f'ekiten_{category_name}',
                        'stage': 'initial',
                        'last_sent_date': '',
                        'initial_sent_date': '',
                        '除外': '',
                    }
                    append_to_csv(row)
                    existing.add(email.lower())
                    total_new += 1
                    logger.info(f"NEW: {email} ({detail['company_name']})")
        
        progress[category_name] = page + 1
        save_progress(progress)
        logger.info(f"Page {page} done. New: {total_new}, Checked: {total_checked}")
    
    logger.info(f"Finished {category_name}. Total new emails: {total_new}, Total checked: {total_checked}")


if __name__ == '__main__':
    cat = sys.argv[1] if len(sys.argv) > 1 else 'clinic'
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    run(category_name=cat, max_pages=pages)
