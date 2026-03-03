#!/usr/bin/env python3
"""
メアド直接掲載ソース調査スクリプト
既存TEL用サイト + 新規候補サイトでメアドが直接表示されているか確認
"""
import re
import requests
from bs4 import BeautifulSoup
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

def check_page_for_emails(url, site_name):
    """ページにアクセスしてメアドが直接表示されているか確認"""
    print(f"\n{'='*60}")
    print(f"調査: {site_name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        print(f"ステータス: HTTP {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"❌ アクセス失敗")
            return
        
        html = resp.text
        soup = BeautifulSoup(html, 'lxml')
        
        # メアド検索
        emails = EMAIL_REGEX.findall(html)
        
        # 除外ドメイン
        exclude = ['example.com', 'schema.org', 'w3.org', 'google', 'facebook', 'twitter', 
                   'instagram', 'linkedin', 'youtube', 'wixpress', 'sentry.io']
        
        valid_emails = []
        for email in emails:
            domain = email.split('@')[1].lower()
            if not any(ex in domain for ex in exclude):
                valid_emails.append(email)
        
        if valid_emails:
            print(f"✓ メアド発見: {len(set(valid_emails))}件")
            for email in set(valid_emails)[:5]:
                print(f"  - {email}")
            if len(set(valid_emails)) > 5:
                print(f"  ... 他 {len(set(valid_emails)) - 5}件")
        else:
            print(f"❌ メアド未発見")
        
        # ページタイトル
        title = soup.find('title')
        if title:
            print(f"ページタイトル: {title.get_text(strip=True)[:80]}")
        
        return len(set(valid_emails)) > 0
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        return False

def main():
    print("="*60)
    print("メアド直接掲載ソース調査")
    print("="*60)
    
    # A. 既存TEL用サイトのサンプルページ
    print("\n\n### A. 既存TEL用サイト調査 ###\n")
    
    existing_sites = [
        ("税理士ドットコム", "https://www.zeiri4.com/c_1/"),
        ("弁護士ドットコム", "https://www.bengo4.com/tokyo/a_13101/l_100001/"),
        ("比較biz", "https://www.biz.ne.jp/"),
        ("アイミツ", "https://imitsu.jp/"),
        ("まほろばプロ", "https://mahoroba-pro.com/"),
    ]
    
    results_existing = {}
    for name, url in existing_sites:
        time.sleep(2)
        has_email = check_page_for_emails(url, name)
        results_existing[name] = has_email
    
    # B. 新規候補サイト
    print("\n\n### B. 新規候補サイト調査 ###\n")
    
    new_sites = [
        ("freee税理士検索", "https://www.freee.co.jp/tax-accountant-search/"),
        ("名簿エンジン", "https://meibo-engine.com/"),
        ("Baseconnect", "https://baseconnect.in/"),
    ]
    
    results_new = {}
    for name, url in new_sites:
        time.sleep(2)
        has_email = check_page_for_emails(url, name)
        results_new[name] = has_email
    
    # サマリー
    print("\n\n" + "="*60)
    print("調査結果サマリー")
    print("="*60)
    
    print("\n### 既存TEL用サイト ###")
    for name, has_email in results_existing.items():
        status = "✓ メアドあり" if has_email else "❌ メアドなし"
        print(f"{name}: {status}")
    
    print("\n### 新規候補サイト ###")
    for name, has_email in results_new.items():
        status = "✓ メアドあり" if has_email else "❌ メアドなし"
        print(f"{name}: {status}")
    
    print("\n" + "="*60)

if __name__ == '__main__':
    main()
