#!/usr/bin/env python3
"""
Green Step 2: Extract company details from company pages
"""
import csv
import json
import os
import re
import sys
import time
import random
from pathlib import Path

import requests
from bs4 import BeautifulSoup

INPUT_FILE = '/opt/libertycall/scraper/output/green_company_ids.txt'
OUTPUT_CSV = '/opt/libertycall/scraper/output/green_companies.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'

CSV_FIELDS = ['company_id', 'company_name', 'address', 'website', 'industry', 'employees', 'green_url']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

def load_existing_companies():
    """既に処理済みの企業IDを取得"""
    existing = set()
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('company_id'):
                    existing.add(row['company_id'])
    return existing

def extract_company_details(company_id):
    """企業詳細ページから情報を抽出"""
    url = f'https://www.green-japan.com/company/{company_id}'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
        
        # 企業名
        name_match = re.search(r'"name":"([^"]+)"', html)
        name = name_match.group(1) if name_match else ''
        
        # 住所
        address_match = re.search(r'"address":"([^"]+)"', html)
        address = address_match.group(1) if address_match else ''
        
        # 公式HP URL（green-japan以外の外部URL）
        url_matches = re.findall(r'https?://([a-z0-9\-]+\.(?:co\.jp|com|net|jp|org|io))', html)
        exclude_domains = ['green-japan', 'google', 'facebook', 'twitter', 'instagram', 'linkedin', 'youtube', 'schema.org', 'atrae.co.jp', 'cloudfront', 'gstatic']
        external_urls = [f'https://{u}' for u in url_matches if not any(ex in u for ex in exclude_domains)]
        website = external_urls[0] if external_urls else ''
        
        # 業種
        industry_match = re.search(r'"industryTypeName":"([^"]+)"', html)
        industry = industry_match.group(1) if industry_match else ''
        
        # 従業員数
        employees_match = re.search(r'"numberOfEmployees":"?([^",}]+)"?', html)
        employees = employees_match.group(1) if employees_match else ''
        
        return {
            'company_id': company_id,
            'company_name': name,
            'address': address,
            'website': website,
            'industry': industry,
            'employees': employees,
            'green_url': url,
        }
    except Exception as e:
        print(f"Error fetching company {company_id}: {e}", flush=True)
        return None

def append_to_csv(row):
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found. Run step1 first.", flush=True)
        return
    
    with open(INPUT_FILE, 'r') as f:
        company_ids = [line.strip() for line in f if line.strip()]
    
    existing = load_existing_companies()
    to_process = [cid for cid in company_ids if cid not in existing]
    
    print(f"Total companies: {len(company_ids)}", flush=True)
    print(f"Already processed: {len(existing)}", flush=True)
    print(f"To process: {len(to_process)}\n", flush=True)
    
    total_success = 0
    total_with_website = 0
    
    for i, company_id in enumerate(to_process, 1):
        print(f"[{i}/{len(to_process)}] Company {company_id}...", end=' ', flush=True)
        
        details = extract_company_details(company_id)
        
        if details:
            append_to_csv(details)
            total_success += 1
            if details['website']:
                total_with_website += 1
                print(f"✓ {details['company_name']} | {details['website']}", flush=True)
            else:
                print(f"✓ {details['company_name']} | No website", flush=True)
        else:
            print(f"✗ Failed", flush=True)
        
        time.sleep(random.uniform(2, 4))
        
        if i % 50 == 0:
            print(f"\n--- Progress: {i}/{len(to_process)} | Success: {total_success} | With website: {total_with_website} ---\n", flush=True)
    
    print(f"\n{'='*60}", flush=True)
    print(f"✓ Processed {total_success} companies", flush=True)
    print(f"✓ Companies with website: {total_with_website}", flush=True)
    print(f"✓ Saved to {OUTPUT_CSV}", flush=True)
    print(f"{'='*60}", flush=True)

if __name__ == '__main__':
    main()
