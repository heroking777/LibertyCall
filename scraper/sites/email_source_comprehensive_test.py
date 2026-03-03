#!/usr/bin/env python3
"""
メアド直接掲載ソース包括調査
実際に動作するURLで詳細ページのメアド表示を確認
"""
import re
import requests
from bs4 import BeautifulSoup
import time
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

def check_page_for_emails(url, site_name, check_json_ld=True):
    """ページにアクセスしてメアドが直接表示されているか確認"""
    print(f"\n{'='*70}")
    print(f"調査: {site_name}")
    print(f"URL: {url}")
    print(f"{'='*70}")
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        print(f"ステータス: HTTP {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"❌ アクセス失敗")
            return {'success': False, 'has_email': False, 'email_count': 0, 'emails': []}
        
        html = resp.text
        soup = BeautifulSoup(html, 'lxml')
        
        # メアド検索（HTML本文）
        emails_html = EMAIL_REGEX.findall(html)
        
        # JSON-LD構造化データからもメアド検索
        emails_jsonld = []
        if check_json_ld:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string)
                    data_str = json.dumps(data)
                    emails_jsonld.extend(EMAIL_REGEX.findall(data_str))
                except:
                    pass
        
        all_emails = emails_html + emails_jsonld
        
        # 除外ドメイン
        exclude = ['example.com', 'schema.org', 'w3.org', 'google', 'facebook', 'twitter', 
                   'instagram', 'linkedin', 'youtube', 'wixpress', 'sentry.io', 'apple.com',
                   'gstatic.com', 'googleapis.com', 'cloudflare.com', 'gravatar.com']
        
        valid_emails = set()
        for email in all_emails:
            email_lower = email.lower()
            domain = email_lower.split('@')[1] if '@' in email_lower else ''
            if domain and not any(ex in domain for ex in exclude):
                valid_emails.add(email_lower)
        
        if valid_emails:
            print(f"✓ メアド発見: {len(valid_emails)}件")
            for email in list(valid_emails)[:10]:
                print(f"  - {email}")
            if len(valid_emails) > 10:
                print(f"  ... 他 {len(valid_emails) - 10}件")
        else:
            print(f"❌ メアド未発見")
        
        # ページタイトル
        title = soup.find('title')
        if title:
            print(f"ページタイトル: {title.get_text(strip=True)[:100]}")
        
        return {
            'success': True,
            'has_email': len(valid_emails) > 0,
            'email_count': len(valid_emails),
            'emails': list(valid_emails)[:5],
            'title': title.get_text(strip=True)[:100] if title else ''
        }
        
    except Exception as e:
        print(f"❌ エラー: {str(e)[:100]}")
        return {'success': False, 'has_email': False, 'email_count': 0, 'emails': [], 'error': str(e)[:100]}

def main():
    print("="*70)
    print("メアド直接掲載ソース包括調査")
    print("="*70)
    
    all_results = {}
    
    # 1. 企業情報サイト
    print("\n\n### 1. 企業情報・求人サイト ###\n")
    
    company_sites = [
        ("iタウンページ - 企業詳細", "https://itp.ne.jp/info/135764364100000899/"),
        ("タウンワーク - 求人詳細", "https://townwork.net/detail/clc_0000000001/joid_00000000001/"),
        ("Indeed - 企業ページ", "https://jp.indeed.com/cmp/Google"),
        ("求人ボックス - 企業詳細", "https://xn--pckua2a7gp15o89zb.com/%E4%BC%81%E6%A5%AD"),
    ]
    
    for name, url in company_sites:
        time.sleep(2)
        result = check_page_for_emails(url, name)
        all_results[name] = result
    
    # 2. 士業マッチングサイト
    print("\n\n### 2. 士業マッチングサイト ###\n")
    
    professional_sites = [
        ("税理士紹介センター", "https://www.zeirishishokai.com/"),
        ("弁護士検索", "https://www.nichibenren.or.jp/"),
        ("行政書士会", "https://www.gyosei.or.jp/"),
    ]
    
    for name, url in professional_sites:
        time.sleep(2)
        result = check_page_for_emails(url, name)
        all_results[name] = result
    
    # 3. ビジネスマッチング・比較サイト
    print("\n\n### 3. ビジネスマッチング・比較サイト ###\n")
    
    matching_sites = [
        ("発注ナビ", "https://hnavi.co.jp/"),
        ("アイミツ - トップ", "https://imitsu.jp/"),
        ("比較biz - トップ", "https://www.biz.ne.jp/"),
    ]
    
    for name, url in matching_sites:
        time.sleep(2)
        result = check_page_for_emails(url, name)
        all_results[name] = result
    
    # 4. 業界団体・協会サイト
    print("\n\n### 4. 業界団体・協会サイト（会員リスト） ###\n")
    
    association_sites = [
        ("日本税理士会連合会", "https://www.nichizeiren.or.jp/"),
        ("全国社会保険労務士会連合会", "https://www.shakaihokenroumushi.jp/"),
        ("日本行政書士会連合会", "https://www.gyosei.or.jp/"),
    ]
    
    for name, url in association_sites:
        time.sleep(2)
        result = check_page_for_emails(url, name)
        all_results[name] = result
    
    # 5. 地域ポータル・商工会議所
    print("\n\n### 5. 地域ポータル・商工会議所 ###\n")
    
    local_sites = [
        ("東京商工会議所", "https://www.tokyo-cci.or.jp/"),
        ("大阪商工会議所", "https://www.osaka.cci.or.jp/"),
    ]
    
    for name, url in local_sites:
        time.sleep(2)
        result = check_page_for_emails(url, name)
        all_results[name] = result
    
    # サマリー
    print("\n\n" + "="*70)
    print("調査結果サマリー")
    print("="*70)
    
    categories = {
        "企業情報・求人サイト": company_sites,
        "士業マッチングサイト": professional_sites,
        "ビジネスマッチング・比較サイト": matching_sites,
        "業界団体・協会サイト": association_sites,
        "地域ポータル・商工会議所": local_sites,
    }
    
    for category, sites in categories.items():
        print(f"\n### {category} ###")
        for name, _ in sites:
            result = all_results.get(name, {})
            if result.get('has_email'):
                print(f"✓ {name}: メアドあり ({result['email_count']}件)")
                if result.get('emails'):
                    print(f"  例: {result['emails'][0]}")
            else:
                status = "アクセス失敗" if not result.get('success') else "メアドなし"
                print(f"❌ {name}: {status}")
    
    # 統計
    print("\n" + "="*70)
    print("統計")
    print("="*70)
    
    total_tested = len(all_results)
    total_success = sum(1 for r in all_results.values() if r.get('success'))
    total_with_email = sum(1 for r in all_results.values() if r.get('has_email'))
    
    print(f"テスト総数: {total_tested}サイト")
    print(f"アクセス成功: {total_success}サイト")
    print(f"メアド直接表示あり: {total_with_email}サイト")
    if total_success > 0:
        print(f"メアド表示率: {total_with_email}/{total_success} = {total_with_email/total_success*100:.1f}%")
    
    # 推奨ソース
    if total_with_email > 0:
        print("\n" + "="*70)
        print("✓ メアド直接表示があるソース（推奨）")
        print("="*70)
        for name, result in all_results.items():
            if result.get('has_email'):
                print(f"\n【{name}】")
                print(f"  メアド数: {result['email_count']}件")
                print(f"  サンプル: {', '.join(result['emails'][:3])}")
    else:
        print("\n" + "="*70)
        print("結論: メアド直接表示のあるソースは見つかりませんでした")
        print("="*70)
        print("\n推奨アプローチ:")
        print("1. 既存の「公式HP→email_extractor」方式を継続")
        print("2. エキテン・Wantedlyなど打率の高いソースに注力")
        print("3. 有料の企業データベースAPI検討（Baseconnect等）")
    
    print("\n" + "="*70)

if __name__ == '__main__':
    main()
