"""
共通メアド抽出エンジン
URLを渡すとHTMLから正規表現でメールアドレスを抽出して返す
トップページになければ /contact /about /company 等を自動巡回
"""

import re
import time
import random
import logging
import socket
import smtplib
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import dns.resolver
    HAS_DNSPYTHON = True
except ImportError:
    HAS_DNSPYTHON = False

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE
)

EXCLUDE_EMAILS = {
    'example.com', 'example.co.jp', 'example.jp', 'sentry.io', 'wixpress.com',
    'googleusercontent.com', 'w3.org', 'schema.org', 'apple.com',
    'googleapis.com', 'gstatic.com',
    'sample.com', 'sample.co.jp', 'test.com', 'dummy.com', 'domain.co.jp', 'your.com', 'yourcompany.com', 's.pe', 'ymobile.jp',
}

# 優先度順のパスリスト（改良A: 拡張版）
CONTACT_PATHS_PRIORITY = [
    # 最優先: お問い合わせ系
    '/contact', '/contact/', '/contact.html', '/contact.php',
    '/inquiry', '/inquiry/', '/inquiry.html',
    '/toiawase', '/toiawase/', '/toiawase.html',
    
    # 高優先: 会社情報系
    '/company', '/company/', '/company.html',
    '/about', '/about/', '/about.html',
    '/aboutus', '/aboutus/', '/aboutus.html',
    '/profile', '/profile/', '/profile.html',
    
    # 中優先: 採用・アクセス系
    '/recruit', '/recruit/', '/recruit.html',
    '/careers', '/careers/', '/careers.html',
    '/jobs', '/jobs/', '/jobs.html',
    '/saiyou', '/saiyou/', '/saiyou.html',
    '/access', '/access/', '/access.html',
    
    # 低優先: その他
    '/info', '/info/', '/info.html',
    '/support', '/support/', '/support.html',
]

# 後方互換性のため
CONTACT_PATHS = CONTACT_PATHS_PRIORITY

TIMEOUT = 15

# 改良A: 2階層クロール設定
MAX_CRAWL_DEPTH = 2
MAX_LINKS_PER_PAGE = 10  # 各ページから抽出するリンク数上限

# 改良B: SMTP推測用の共通プレフィックス
COMMON_EMAIL_PREFIXES = ['info', 'contact', 'sales', 'support', 'admin', 'mail', 'inquiry', 'office', 'webmaster', 'hello', 'post']


def _clean_email(email):
    """JSゴミ除去して綺麗なメールアドレスを返す"""
    email = re.split(r"[',;)\]}>]", email)[0].strip()
    return email

def _is_valid_email(email):
    email = _clean_email(email)
    if not email or '@' not in email:
        return False

    # URLエンコード混入
    if '%' in email:
        return False

    local, domain = email.rsplit('@', 1)

    # 基本フォーマット
    if not local or not domain or '.' not in domain:
        return False
    if len(email) < 6 or len(email) > 80:
        return False
    if '..' in email:
        return False

    domain_lower = domain.lower()

    # 除外ドメイン
    if domain_lower in EXCLUDE_EMAILS:
        return False
    for excl in EXCLUDE_EMAILS:
        if domain_lower.endswith('.' + excl):
            return False

    # 画像・メディアファイル拡張子（srcset誤検出対策）
    MEDIA_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif',
                  '.ico', '.bmp', '.tiff', '.mp4', '.mp3', '.pdf', '.css', '.js')
    if any(domain_lower.endswith(ext) for ext in MEDIA_EXTS):
        return False
    if any(email.lower().endswith(ext) for ext in MEDIA_EXTS):
        return False

    # ドメインが短すぎる (x.xx 等)
    parts = domain_lower.split('.')
    if len(parts) < 2 or len(parts[0]) < 2:
        return False

    # 数字のみのローカルパート (0783330003@ 等)
    if re.match(r'^[\d]+$', local) and len(local) > 6:
        return False

    # ハッシュ・ランダム文字列 (10956296.cf7a03bb... 等)
    if re.match(r'^[0-9a-f]{6,}\.[0-9a-f]{6,}', local):
        return False

    # サイズ指定パターン (300x171, 2x, 3x 等 = srcset由来)
    if re.search(r'\d+x\d+', email) or re.search(r'@\d+x\.', email):
        return False

    # テスト用ローカルパート
    if local.lower() in ('sample', 'test', 'example', 'dummy', 'xxx', 'name', 'email'):
        return False

    # TLDが2文字未満 or 存在しないパターン（.bbb等）
    tld = parts[-1]
    VALID_SHORT_TLDS = {'co', 'jp', 'ch', 'uk', 'de', 'fr', 'it', 'es', 'nl', 'se',
                        'no', 'dk', 'fi', 'at', 'be', 'pt', 'ie', 'au', 'nz', 'sg',
                        'hk', 'in', 'th', 'vn', 'id', 'ph', 'my', 'br', 'mx', 'ar',
                        'kr', 'cn', 'tw', 'ru', 'us', 'ca', 'za', 'pl', 'cz', 'hu',
                        'gr', 'ro', 'bg', 'hr', 'sk', 'si', 'lt', 'lv', 'ee', 'io',
                        'ai', 'me', 'tv', 'cc', 'to', 'fm', 'am', 'ly', 'sh', 'sx',
                        'kz', 'sz', 'pe'}
    if len(tld) <= 3 and tld not in VALID_SHORT_TLDS and tld not in ('com', 'net', 'org', 'edu', 'gov', 'mil', 'int', 'biz', 'pro', 'xyz'):
        return False

    # ローカルパートが数字のみで3文字以下
    if local.isdigit() and len(local) <= 3:
        return False

    return True


def _extract_emails_from_html(html):
    soup = BeautifulSoup(html, 'lxml')
    emails = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'mailto:' in href:
            addr = href.split('mailto:')[1].split('?')[0].strip()
            addr = _clean_email(addr)
            if EMAIL_REGEX.match(addr) and _is_valid_email(addr):
                emails.add(addr.lower())
    for match in EMAIL_REGEX.findall(html):
        cleaned = _clean_email(match)
        if _is_valid_email(cleaned):
            emails.add(cleaned.lower())
    return emails


def _fetch_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.debug(f"Fetch failed: {url} - {e}")
        return None


def _get_mx_host(domain):
    """ドメインのMXホストを取得"""
    if not HAS_DNSPYTHON:
        return None
    
    try:
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx_host = str(mx_records[0].exchange).rstrip('.')
        return mx_host
    except:
        # MXレコードがない場合はAレコードを試す
        try:
            dns.resolver.resolve(domain, 'A')
            return domain
        except:
            logger.debug(f"No MX/A record for {domain}")
            return None


def _is_catchall_domain(domain, mx_host):
    """Catch-allサーバー検出（ランダム文字列で250が返るか）"""
    import string
    random_local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=20))
    test_email = f"{random_local}@{domain}"
    
    try:
        server = smtplib.SMTP(timeout=3)
        server.connect(mx_host, 25)
        server.helo('libcall.com')
        server.mail('verify@libcall.com')
        code, _ = server.rcpt(test_email)
        server.quit()
        
        if code in (250, 251):
            logger.debug(f"Catch-all detected for {domain}")
            return True
        return False
    except Exception as e:
        logger.debug(f"Catch-all test failed for {domain}: {e}")
        return False


def _verify_email_smtp(email, mx_host):
    """改良B: SMTP検証でメアドの存在確認"""
    try:
        server = smtplib.SMTP(timeout=3)
        server.connect(mx_host, 25)
        server.helo('libcall.com')
        server.mail('verify@libcall.com')
        code, _ = server.rcpt(email)
        server.quit()
        
        # 250 = OK, 251 = User not local (but OK)
        if code in (250, 251):
            logger.debug(f"SMTP verified: {email} (code {code})")
            return True
        elif code == 550:
            logger.debug(f"SMTP rejected: {email} (code 550 - not found)")
            return False
        else:
            logger.debug(f"SMTP uncertain: {email} (code {code})")
            return False
    except Exception as e:
        logger.debug(f"SMTP connection failed for {email}: {e}")
        return False


def _guess_emails_smtp(website_url):
    """改良B: Webクロールで見つからない場合、SMTP推測でメアドを生成・検証"""
    if not HAS_DNSPYTHON:
        logger.debug("dnspython not installed, skipping SMTP guessing")
        return []
    
    try:
        # ドメイン抽出
        parsed = urlparse(website_url)
        domain = parsed.netloc
        # www.を除去
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain:
            return []
        
        # MXレコード取得
        mx_host = _get_mx_host(domain)
        if not mx_host:
            logger.debug(f"No MX host for {domain}")
            return []
        
        # Catch-all検出（catch-allでもinfo@は採用）
        if _is_catchall_domain(domain, mx_host):
            logger.debug(f"Catch-all: {domain} - using info@ only")
            return [f"info@{domain}"]
        
        # info@を最優先で試す（成功したら即return）
        info_candidate = f"info@{domain}"
        if _verify_email_smtp(info_candidate, mx_host):
            logger.debug(f"SMTP guessed (fast): {info_candidate}")
            return [info_candidate]
        
        # info@失敗なら主要3つだけ試す
        for prefix in ['contact', 'mail', 'support']:
            candidate = f"{prefix}@{domain}"
            time.sleep(random.uniform(0.5, 1))
            if _verify_email_smtp(candidate, mx_host):
                logger.debug(f"SMTP guessed: {candidate}")
                return [candidate]
        
        return []
        
    except Exception as e:
        logger.debug(f"SMTP guessing error for {website_url}: {e}")
        return []


def _extract_internal_links(html, base_url):
    """改良A: ページ内の内部リンクを抽出"""
    soup = BeautifulSoup(html, 'lxml')
    links = set()
    base_domain = urlparse(base_url).netloc
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        # 同一ドメインの内部リンクのみ
        if parsed.netloc == base_domain:
            # フラグメント除去
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            links.add(clean_url)
        
        if len(links) >= MAX_LINKS_PER_PAGE:
            break
    
    return list(links)


def extract_emails(website_url, deep_search=True, smtp_guess=False):
    """
    メアド抽出メイン関数
    
    Args:
        website_url: 対象WebサイトURL
        deep_search: True=2階層クロール有効（改良A）
        smtp_guess: True=SMTP検証有効（改良B）
    
    Returns:
        list: 抽出されたメアドリスト（優先度順、最大3件）
    """
    if not website_url:
        return []
    if not website_url.startswith('http'):
        website_url = 'https://' + website_url
    
    all_emails = set()
    visited_urls = set()
    
    # トップページ取得
    html = _fetch_page(website_url)
    visited_urls.add(website_url)
    
    if html:
        all_emails.update(_extract_emails_from_html(html))
    
    # 改良A: deep_search有効時は2階層クロール
    if deep_search and html:
        # 第1階層: 優先パスを巡回
        if not all_emails:
            for p in CONTACT_PATHS_PRIORITY:
                sub_url = urljoin(website_url, p)
                if sub_url in visited_urls:
                    continue
                
                time.sleep(random.uniform(0.5, 1))
                sub_html = _fetch_page(sub_url)
                visited_urls.add(sub_url)
                
                if sub_html:
                    all_emails.update(_extract_emails_from_html(sub_html))
                
                if all_emails:
                    break
        
        # 第2階層: まだメアドが見つからない場合、内部リンクを探索
        if not all_emails and MAX_CRAWL_DEPTH >= 2:
            internal_links = _extract_internal_links(html, website_url)
            
            # 優先キーワードを含むリンクを優先
            priority_keywords = ['contact', 'about', 'company', 'inquiry', 'recruit', 'toiawase']
            priority_links = []
            other_links = []
            
            for link in internal_links:
                if link in visited_urls:
                    continue
                link_lower = link.lower()
                if any(kw in link_lower for kw in priority_keywords):
                    priority_links.append(link)
                else:
                    other_links.append(link)
            
            # 優先リンクから探索
            for link in (priority_links + other_links)[:5]:  # 最大5リンク
                if all_emails:
                    break
                
                time.sleep(random.uniform(0.5, 1))
                link_html = _fetch_page(link)
                visited_urls.add(link)
                
                if link_html:
                    all_emails.update(_extract_emails_from_html(link_html))
    
    # 改良B: Webクロールで見つからない場合、SMTP推測
    if not all_emails and smtp_guess:
        logger.debug(f"No emails found via web crawl, trying SMTP guessing for {website_url}")
        guessed_emails = _guess_emails_smtp(website_url)
        all_emails.update(guessed_emails)
    
    if not all_emails:
        return []
    
    # 優先度ソート
    result = sorted(all_emails)
    priority = []
    others = []
    for e in result:
        local = e.split('@')[0].lower()
        if local in ('info', 'contact', 'mail', 'support', 'office', 'inquiry', 'recruit'):
            priority.append(e)
        else:
            others.append(e)
    
    return (priority + others)[:3]


if __name__ == '__main__':
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.fujizemi.jp/'
    print(f"Testing: {url}")
    emails = extract_emails(url)
    print(f"Found: {emails}")
