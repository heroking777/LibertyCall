#!/usr/bin/env python3
"""
Green Step 1: Extract all company IDs from listing pages
"""
import re
import requests
import time
from pathlib import Path

SEARCH_URL = 'https://www.green-japan.com/search'
OUTPUT_FILE = '/opt/libertycall/scraper/output/green_company_ids.txt'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

def fetch_company_ids_from_page(page):
    """指定ページから企業IDを抽出"""
    params = {'page': page}
    try:
        resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        company_ids = re.findall(r'/company/(\d+)', resp.text)
        return list(set(company_ids))
    except Exception as e:
        print(f"Error fetching page {page}: {e}", flush=True)
        return []

def main():
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    
    all_company_ids = set()
    page = 1
    consecutive_empty = 0
    
    print("Starting Green company ID extraction...\n", flush=True)
    
    while True:
        print(f"Processing page {page}...", end=' ', flush=True)
        company_ids = fetch_company_ids_from_page(page)
        
        if not company_ids:
            consecutive_empty += 1
            print(f"No companies found (empty count: {consecutive_empty})", flush=True)
            if consecutive_empty >= 3:
                print("3 consecutive empty pages, stopping.", flush=True)
                break
        else:
            consecutive_empty = 0
            new_ids = [cid for cid in company_ids if cid not in all_company_ids]
            all_company_ids.update(company_ids)
            print(f"Found {len(company_ids)} companies ({len(new_ids)} new) | Total: {len(all_company_ids)}", flush=True)
        
        page += 1
        time.sleep(2)
        
        # Safety limit
        if page > 1000:
            print("Reached page limit (1000), stopping.", flush=True)
            break
    
    # Save to file
    with open(OUTPUT_FILE, 'w') as f:
        for company_id in sorted(all_company_ids, key=int):
            f.write(company_id + '\n')
    
    print(f"\n{'='*60}", flush=True)
    print(f"✓ Extracted {len(all_company_ids)} unique company IDs", flush=True)
    print(f"✓ Saved to {OUTPUT_FILE}", flush=True)
    print(f"{'='*60}", flush=True)

if __name__ == '__main__':
    main()
