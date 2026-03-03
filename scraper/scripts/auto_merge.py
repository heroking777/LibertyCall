#!/usr/bin/env python3
"""searxng_emails.csv → master_leads.csv 自動マージ（重複チェック付き）"""
import csv
import os
import fcntl
from datetime import datetime

SEARXNG_CSV = '/opt/libertycall/scraper/output/searxng_emails.csv'
MASTER_CSV = '/opt/libertycall/email_sender/data/master_leads.csv'
MERGE_LOG = '/opt/libertycall/scraper/logs/merge.log'

def log(msg):
    os.makedirs(os.path.dirname(MERGE_LOG), exist_ok=True)
    with open(MERGE_LOG, 'a') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

def main():
    # master既存メール読み込み
    master_emails = set()
    master_rows = []
    header = None
    with open(MASTER_CSV, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            master_rows.append(row)
            if row and '@' in row[0]:
                master_emails.add(row[0].lower().strip())

    # searxng新規取得
    new_rows = []
    dupes = 0
    seen = set()
    with open(SEARXNG_CSV, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # ヘッダースキップ
        for row in reader:
            if not row or '@' not in row[0]:
                continue
            email = row[0].lower().strip()
            if email in master_emails or email in seen:
                dupes += 1
                continue
            seen.add(email)
            # 7列に揃える
            if len(row) >= 7:
                new_rows.append(row[:7])
            else:
                row.extend([''] * (7 - len(row)))
                new_rows.append(row[:7])

    if not new_rows:
        log(f"新規なし（重複{dupes}件スキップ）")
        return

    # masterに追記（ロック付き）
    with open(MASTER_CSV, 'a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        writer = csv.writer(f)
        writer.writerows(new_rows)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    total = len(master_rows) + len(new_rows)
    log(f"マージ完了: +{len(new_rows)}件（重複{dupes}件スキップ）合計{total}件")
    print(f"マージ完了: +{len(new_rows)}件 | 重複スキップ: {dupes}件 | 合計: {total}件")

if __name__ == '__main__':
    main()
