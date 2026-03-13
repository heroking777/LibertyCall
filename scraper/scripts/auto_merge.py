#!/usr/bin/env python3
"""searxng_emails.csv → master_leads.csv 自動マージ（重複・除外・品質チェック付き）"""
import csv
import os
import re
import fcntl
from datetime import datetime

SEARXNG_CSV = '/opt/libertycall/scraper/output/searxng_emails.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'
UNSUB_CSV = '/opt/libertycall/unsubscribe_list.csv'
MERGE_LOG = '/opt/libertycall/scraper/logs/merge.log'

# フリーメール・無効ドメイン
INVALID_DOMAINS = {
    'gmail.com','yahoo.com','yahoo.co.jp','hotmail.com','outlook.com',
    'icloud.com','ymail.com','aol.com','live.com','live.jp',
    'me.com','mac.com','msn.com','protonmail.com','zoho.com',
    'mail.com','email.com','example.com','test.com','localhost',
    'wise.com','xero.com','hotcopper.com.au','wikipedia.de','dominos.ca',
    'pizzahut.co.uk','standardlife.co.uk','rightmove.co.uk','dailymail.co.uk',
    'pizzapizza.ca','sina.com.cn','yandex.ru','ya.ru','nps.gov','sec.gov',
    'fda.gov','cdc.gov','nasa.gov','commerce.gov','va.gov','coronaca.gov',
    'spotify.com','netflix.com','amazon.com','google.com','facebook.com',
    'twitter.com','instagram.com','tiktok.com','linkedin.com','apple.com',
    'microsoft.com','github.com','slack.com','zoom.us','dropbox.com',
    'stripe.com','paypal.com','shopify.com','hubspot.com','salesforce.com',
    'zendesk.com','intercom.com','twilio.com','mailchimp.com','sendgrid.com',
    'cloudflare.com','digitalocean.com','heroku.com','vercel.com',
    'wordpress.com','medium.com','reddit.com','quora.com','pinterest.com',
    'tumblr.com','flickr.com','vimeo.com','youtube.com','whatsapp.com',
    'telegram.org','signal.org','discord.com','twitch.tv',
    'modrinth.com','fitbit.com','justanswer.com','justanswer.jp','iherb.com',
}

INVALID_TLDS = {'.gov','.edu','.mil','.ac.jp','.ru','.br','.cn','.de','.fr','.it','.es','.pt','.se','.nl','.au','.nz','.uk','.us','.sg','.tw','.hk','.th','.vn','.id','.ph','.my','.ca','.kr','.eu','.int'}

INVALID_EMAIL_PATTERNS = [
    r'^xxx@', r'^name@', r'^email@', r'^test@', r'^sample@',
    r'^admin@admin', r'^info@info\.', r'^noreply@', r'^no-reply@', r'^support@', r'^postmaster@', r'^abuse@', r'^webmaster@', r'^hostmaster@',
    r'^donotreply@', r'^mailer-daemon@', r'^postmaster@',
    r'^abuse@', r'^null@', r'^root@',
    r'@xxxx\.', r'@xxx\.', r'@example\.',
]

def log(msg):
    os.makedirs(os.path.dirname(MERGE_LOG), exist_ok=True)
    with open(MERGE_LOG, 'a') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

def is_valid_email(email):
    """メールアドレスの品質チェック"""
    if not email or '@' not in email:
        return False
    local, domain = email.rsplit('@', 1)
    if not local or not domain or '.' not in domain:
        return False
    if len(email) < 6 or len(email) > 254:
        return False
    if domain.lower() in INVALID_DOMAINS or domain.lower() in COMPETITOR_DOMAINS:
        return False
    for tld in INVALID_TLDS:
        if domain.lower().endswith(tld):
            return False
    for pat in INVALID_EMAIL_PATTERNS:
        if re.search(pat, email.lower()):
            return False
    # 画像・メディアファイル拡張子
    MEDIA_EXTS = ('.webp','.jpeg','.jpg','.png','.gif','.svg','.avif','.ico','.css','.js','.pdf','.mp4','.mp3')
    if any(email.lower().endswith(ext) for ext in MEDIA_EXTS):
        return False
    # srcsetパターン (@2x, 300x171 等)
    if re.search(r'@\d+x\.', email) or re.search(r'\d+x\d+', email):
        return False
    # ローカルパートが数字のみで6文字超
    if re.match(r'^[\d]+$', local) and len(local) > 6:
        return False
    # ハッシュ文字列 (10956296.cf7a03bb... 等)
    if re.match(r'^[0-9a-f]{6,}\.[0-9a-f]{6,}', local):
        return False
    return True

# 競合ドメインリスト読み込み
COMPETITOR_DOMAINS = set()
_comp_path = '/opt/libertycall/scraper/data/competitor_domains.txt'
try:
    with open(_comp_path, 'r') as _f:
        for _line in _f:
            _d = _line.strip().lower()
            if _d:
                COMPETITOR_DOMAINS.add(_d)
except FileNotFoundError:
    pass

def load_excluded_emails():
    """除外すべきメールアドレスを収集"""
    excluded = set()
    if os.path.exists(UNSUB_CSV):
        with open(UNSUB_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get('email', '').strip().lower()
                if email:
                    excluded.add(email)
    if os.path.exists(MASTER_CSV):
        with open(MASTER_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get('除外') or '').strip():
                    email = row.get('email', '').strip().lower()
                    if email:
                        excluded.add(email)
    return excluded

def main():
    excluded_emails = load_excluded_emails()
    master_emails = set()
    master_rows = []
    with open(MASTER_CSV, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            master_rows.append(row)
            if row and '@' in row[0]:
                master_emails.add(row[0].lower().strip())

    new_rows = []
    dupes = 0
    excluded_count = 0
    invalid_count = 0
    seen = set()
    with open(SEARXNG_CSV, 'r') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row or '@' not in row[0]:
                continue
            email = row[0].lower().strip()
            if email in master_emails or email in seen:
                dupes += 1
                continue
            if email in excluded_emails:
                excluded_count += 1
                continue
            if not is_valid_email(email):
                invalid_count += 1
                continue
            seen.add(email)
            if len(row) >= 7:
                new_rows.append(row[:7])
            else:
                row.extend([''] * (7 - len(row)))
                new_rows.append(row[:7])

    if not new_rows:
        log(f"新規なし（重複{dupes}件, 除外{excluded_count}件, 無効{invalid_count}件スキップ）")
        return

    with open(MASTER_CSV, 'a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        writer = csv.writer(f)
        writer.writerows(new_rows)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    total = len(master_rows) + len(new_rows)
    log(f"マージ完了: +{len(new_rows)}件（重複{dupes}件, 除外{excluded_count}件, 無効{invalid_count}件スキップ）合計{total}件")
    print(f"マージ完了: +{len(new_rows)}件 | 重複: {dupes} | 除外: {excluded_count} | 無効: {invalid_count} | 合計: {total}")

if __name__ == '__main__':
    main()
