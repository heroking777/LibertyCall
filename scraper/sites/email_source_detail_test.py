#!/usr/bin/env python3
"""
メアド直接掲載ソース調査 - 詳細ページ版
プロフィールページ・企業詳細ページでメアドが直接表示されているか確認
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
            return False, 0
        
        html = resp.text
        soup = BeautifulSoup(html, 'lxml')
        
        # メアド検索
        emails = EMAIL_REGEX.findall(html)
        
        # 除外ドメイン
        exclude = ['example.com', 'schema.org', 'w3.org', 'google', 'facebook', 'twitter', 
                   'instagram', 'linkedin', 'youtube', 'wixpress', 'sentry.io', 'apple.com',
                   'gstatic.com', 'googleapis.com']
        
        valid_emails = set()
        for email in emails:
            domain = email.split('@')[1].lower()
            if not any(ex in domain for ex in exclude):
                valid_emails.add(email.lower())
        
        if valid_emails:
            print(f"✓ メアド発見: {len(valid_emails)}件")
            for email in list(valid_emails)[:5]:
                print(f"  - {email}")
            if len(valid_emails) > 5:
                print(f"  ... 他 {len(valid_emails) - 5}件")
        else:
            print(f"❌ メアド未発見")
        
        # ページタイトル
        title = soup.find('title')
        if title:
            print(f"ページタイトル: {title.get_text(strip=True)[:80]}")
        
        return len(valid_emails) > 0, len(valid_emails)
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        return False, 0

def main():
    print("="*60)
    print("メアド直接掲載ソース調査 - 詳細ページ版")
    print("="*60)
    
    # A. 既存TEL用サイトの詳細ページ
    print("\n\n### A. 既存TEL用サイト - 詳細ページ調査 ###\n")
    
    detail_pages = [
        # 税理士ドットコム - 税理士プロフィール
        ("税理士ドットコム - 税理士プロフィール", "https://www.zeiri4.com/c_1013/h_1001/"),
        
        # 弁護士ドットコム - 弁護士プロフィール
        ("弁護士ドットコム - 弁護士プロフィール", "https://www.bengo4.com/tokyo/a_13101/l_127898/"),
        
        # 比較biz - 企業詳細
        ("比較biz - 企業詳細", "https://www.biz.ne.jp/matome/2001001/"),
        
        # アイミツ - 企業詳細
        ("アイミツ - 企業詳細", "https://imitsu.jp/list/web-production/tokyo/"),
        
        # Green - 企業詳細（既存で使用中）
        ("Green - 企業詳細", "https://www.green-japan.com/company/10001"),
    ]
    
    results_detail = {}
    for name, url in detail_pages:
        time.sleep(2)
        has_email, count = check_page_for_emails(url, name)
        results_detail[name] = (has_email, count)
    
    # B. 新規候補サイト - 詳細ページ
    print("\n\n### B. 新規候補サイト - 詳細ページ調査 ###\n")
    
    new_detail_pages = [
        # freee税理士検索 - 税理士詳細
        ("freee税理士検索 - 税理士詳細", "https://advisors-freee.jp/user/100001"),
        
        # 士業ポータル
        ("士業ポータル - 税理士", "https://shigyo-portal.com/"),
        
        # 企業データベース系
        ("企業データベース例", "https://www.houjin-bangou.nta.go.jp/"),
    ]
    
    results_new = {}
    for name, url in new_detail_pages:
        time.sleep(2)
        has_email, count = check_page_for_emails(url, name)
        results_new[name] = (has_email, count)
    
    # C. 追加調査: エキテン詳細ページ（既存で使用中）
    print("\n\n### C. 既存使用中ソース - 詳細ページ確認 ###\n")
    
    existing_sources = [
        ("エキテン - 店舗詳細", "https://www.ekiten.jp/shop_1000001/"),
        ("Wantedly - 企業詳細", "https://www.wantedly.com/companies/wantedly"),
    ]
    
    results_existing = {}
    for name, url in existing_sources:
        time.sleep(2)
        has_email, count = check_page_for_emails(url, name)
        results_existing[name] = (has_email, count)
    
    # サマリー
    print("\n\n" + "="*60)
    print("調査結果サマリー")
    print("="*60)
    
    print("\n### A. 既存TEL用サイト - 詳細ページ ###")
    for name, (has_email, count) in results_detail.items():
        status = f"✓ メアドあり ({count}件)" if has_email else "❌ メアドなし"
        print(f"{name}: {status}")
    
    print("\n### B. 新規候補サイト - 詳細ページ ###")
    for name, (has_email, count) in results_new.items():
        status = f"✓ メアドあり ({count}件)" if has_email else "❌ メアドなし"
        print(f"{name}: {status}")
    
    print("\n### C. 既存使用中ソース（参考） ###")
    for name, (has_email, count) in results_existing.items():
        status = f"✓ メアドあり ({count}件)" if has_email else "❌ メアドなし"
        print(f"{name}: {status}")
    
    # 結論
    print("\n" + "="*60)
    print("結論")
    print("="*60)
    
    total_with_email = sum(1 for _, (has, _) in {**results_detail, **results_new}.items() if has)
    total_tested = len(results_detail) + len(results_new)
    
    print(f"詳細ページテスト: {total_tested}サイト")
    print(f"メアド直接表示あり: {total_with_email}サイト")
    print(f"打率: {total_with_email}/{total_tested} = {total_with_email/total_tested*100:.1f}%")
    
    if total_with_email > 0:
        print("\n✓ メアド直接表示があるソース:")
        for name, (has, count) in {**results_detail, **results_new}.items():
            if has:
                print(f"  - {name} ({count}件)")
    
    print("\n" + "="*60)

if __name__ == '__main__':
    main()
