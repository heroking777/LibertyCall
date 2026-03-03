#!/usr/bin/env python3
"""
Green Step 2 TEST: Extract details from first 10 companies
"""
import csv
import os
import re
import time
import random

import requests

INPUT_FILE = '/tmp/green_test_10.txt'
OUTPUT_CSV = '/tmp/green_test_companies.csv'

CSV_FIELDS = ['company_id', 'company_name', 'address', 'website', 'industry', 'employees', 'green_url']

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

def extract_company_details(company_id):
    url = f'https://www.green-japan.com/company/{company_id}'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
        
        name_match = re.search(r'"name":"([^"]+)"', html)
        name = name_match.group(1) if name_match else ''
        
        address_match = re.search(r'"address":"([^"]+)"', html)
        address = address_match.group(1) if address_match else ''
        
        url_matches = re.findall(r'https?://([a-z0-9\-]+\.(?:co\.jp|com|net|jp|org|io))', html)
        exclude_domains = ['green-japan', 'google', 'facebook', 'twitter', 'instagram', 'linkedin', 'youtube', 'schema.org', 'atrae.co.jp', 'cloudfront', 'gstatic']
        external_urls = [f'https://{u}' for u in url_matches if not any(ex in u for ex in exclude_domains)]
        website = external_urls[0] if external_urls else ''
        
        industry_match = re.search(r'"industryTypeName":"([^"]+)"', html)
        industry = industry_match.group(1) if industry_match else ''
        
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
        print(f"Error: {e}")
        return None

def main():
    if os.path.exists(OUTPUT_CSV):
        os.remove(OUTPUT_CSV)
    
    with open(INPUT_FILE, 'r') as f:
        company_ids = [line.strip() for line in f if line.strip()]
    
    print(f"Testing with {len(company_ids)} companies\n")
    
    total_success = 0
    total_with_website = 0
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        
        for i, company_id in enumerate(company_ids, 1):
            print(f"[{i}/{len(company_ids)}] Company {company_id}")
            
            details = extract_company_details(company_id)
            
            if details:
                writer.writerow(details)
                total_success += 1
                if details['website']:
                    total_with_website += 1
                    print(f"  ✓ {details['company_name']}")
                    print(f"  Website: {details['website']}")
                else:
                    print(f"  ✓ {details['company_name']}")
                    print(f"  ✗ No website")
            else:
                print(f"  ✗ Failed")
            
            print()
            time.sleep(random.uniform(2, 3))
    
    print(f"\n{'='*60}")
    print(f"TEST COMPLETE: {total_success}/{len(company_ids)} companies extracted")
    print(f"Companies with website: {total_with_website}")
    print(f"Output: {OUTPUT_CSV}")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
