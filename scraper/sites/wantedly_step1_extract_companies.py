#!/usr/bin/env python3
"""
Wantedly Step 1: Extract all company info from API
"""
import json
import requests
import time
from pathlib import Path

API_URL = 'https://www.wantedly.com/api/v1/projects'
OUTPUT_FILE = '/opt/libertycall/scraper/output/wantedly_companies_raw.jsonl'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

def fetch_projects_page(page, per_page=100):
    params = {
        'type': 'mixed',
        'page': page,
        'per_page': per_page,
    }
    try:
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching page {page}: {e}")
        return None

def main():
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    
    companies_seen = set()
    total_projects = None
    page = 1
    
    with open(OUTPUT_FILE, 'w') as f:
        while True:
            data = fetch_projects_page(page)
            if not data:
                break
            
            if total_projects is None:
                total_projects = data.get('_metadata', {}).get('total_objects', 0)
                print(f"Total projects available: {total_projects:,}")
            
            projects = data.get('data', [])
            if not projects:
                break
            
            for project in projects:
                company = project.get('company', {})
                company_id = company.get('id')
                if company_id and company_id not in companies_seen:
                    companies_seen.add(company_id)
                    company_data = {
                        'id': company_id,
                        'name': company.get('name', ''),
                        'url': company.get('url', ''),
                        'address': f"{company.get('address_prefix', '')} {company.get('address_suffix', '')}".strip(),
                        'founded_on': company.get('founded_on', ''),
                        'payroll_number': company.get('payroll_number', 0),
                    }
                    f.write(json.dumps(company_data, ensure_ascii=False) + '\n')
            
            print(f"Page {page}: {len(projects)} projects, {len(companies_seen)} unique companies so far")
            
            page += 1
            time.sleep(2)
            
            if page > 16000:
                break
    
    print(f"\n✓ Extracted {len(companies_seen):,} unique companies")
    print(f"✓ Saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
