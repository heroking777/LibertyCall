#!/usr/bin/env python3
"""Step1: gBizINFO企業名 → SearXNG検索 → ドメイン取得（安定運用版）"""

import csv
import os
import sys
import time
import random
import json
import requests
from urllib.parse import urlparse
from datetime import datetime

INPUT_CSV = '/opt/libertycall/scraper/data/gbizinfo_companies.csv'
OUTPUT_TSV = '/opt/libertycall/scraper/data/domains_found.tsv'
DONE_FILE = '/opt/libertycall/scraper/data/step1_done.txt'
ENGINE_LOG = '/opt/libertycall/scraper/logs/engine_status.log'
SEARXNG_URL = 'http://localhost:8888/search'

# 実績のある3エンジンだけ使用
ENGINES = ['yahoo', 'duckduckgo', 'google', 'bing', 'yandex', 'alexandria']

engine_stats = {}
for e in ENGINES:
    engine_stats[e] = {
        'success': 0,
        'fail': 0,
        'consecutive_fail': 0,
        'disabled': False,
        'disabled_at': None,
    }

MAX_CONSECUTIVE_FAIL = 5
RETRY_AFTER = 7200  # 2時間で復帰試行

SKIP_DOMAINS = {
    'wikipedia.org', 'facebook.com', 'twitter.com', 'instagram.com',
    'youtube.com', 'linkedin.com', 'tiktok.com', 'amazon.co.jp',
    'rakuten.co.jp', 'wantedly.com', 'en-japan.com', 'mynavi.jp',
    'rikunabi.com', 'doda.jp', 'type.jp', 'green-japan.com',
    'indeed.com', 'glassdoor.com', 'bunshun.jp', 'nikkei.com',
    'news.yahoo.co.jp', 'baseconnect.in', 'houjin-bangou.nta.go.jp',
    'prtimes.jp', 'note.com', 'hatena.ne.jp', 'qiita.com',
    'zenn.dev', 'github.com', 'x.com', 'line.me',
    'google.com', 'google.co.jp', 'bing.com',
    'homes.co.jp', 'suumo.jp', 'tabelog.com', 'hotpepper.jp',
    'gnavi.co.jp', 'recruit.co.jp', 'mapion.co.jp', 'houjin.info',
}

def load_done():
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE, 'r') as f:
            return set(f.read().strip().split('\n'))
    return set()

def log_engine(msg):
    with open(ENGINE_LOG, 'a') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

def get_active_engine():
    now = time.time()
    for e in ENGINES:
        s = engine_stats[e]
        if s['disabled'] and s['disabled_at'] and (now - s['disabled_at']) > RETRY_AFTER:
            s['disabled'] = False
            s['consecutive_fail'] = 0
            log_engine(f"RETRY {e} 復帰試行（2時間経過）")

    active = [e for e in ENGINES if not engine_stats[e]['disabled']]
    if not active:
        log_engine("ALL_DOWN 全エンジン停止。2時間待機後リセット")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 全エンジン停止。2時間待機...")
        time.sleep(RETRY_AFTER)
        for e in ENGINES:
            engine_stats[e]['disabled'] = False
            engine_stats[e]['consecutive_fail'] = 0
        log_engine("RESET 全エンジンリセット")
        active = ENGINES[:]
    return active

engine_cycle = 0

def search_domain(company_name):
    global engine_cycle
    active = get_active_engine()
    engine = active[engine_cycle % len(active)]
    engine_cycle += 1

    try:
        resp = requests.get(SEARXNG_URL, params={
            'q': f'{company_name} 公式サイト',
            'format': 'json',
            'engines': engine
        }, timeout=10)

        if resp.status_code != 200:
            mark_fail(engine, f"status={resp.status_code} query={company_name}")
            return None, None, engine

        data = resp.json()
        results = data.get('results', [])

        if not results:
            mark_fail(engine, f"empty query={company_name}")
            return None, None, engine

        for r in results[:3]:
            url = r.get('url', '')
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            if domain and not any(domain.endswith(skip) for skip in SKIP_DOMAINS):
                mark_success(engine)
                return domain, url, engine

        mark_fail(engine, f"no_valid_domain query={company_name}")
        return None, None, engine
    except Exception as e:
        mark_fail(engine, f"error={str(e)[:80]}")
        return None, None, engine

def mark_success(engine):
    s = engine_stats[engine]
    s['success'] += 1
    s['consecutive_fail'] = 0

def mark_fail(engine, reason):
    s = engine_stats[engine]
    s['fail'] += 1
    s['consecutive_fail'] += 1
    if s['consecutive_fail'] >= MAX_CONSECUTIVE_FAIL and not s['disabled']:
        s['disabled'] = True
        s['disabled_at'] = time.time()
        active_count = len([e for e in ENGINES if not engine_stats[e]['disabled']])
        msg = f"DISABLED {engine} ({s['consecutive_fail']}連続失敗) 残り稼働:{active_count}エンジン"
        log_engine(msg)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    else:
        log_engine(f"FAIL {engine} {reason}")

def main():
    os.makedirs(os.path.dirname(ENGINE_LOG), exist_ok=True)
    done = load_done()
    print(f"処理済み: {len(done)}社")
    log_engine(f"=== Step1起動（安定版） 処理済み:{len(done)}社 エンジン:{ENGINES} ===")

    processed = 0
    domains_found = 0

    try:
        with open(INPUT_CSV, 'r') as infile:
            for line in infile:
                parts = line.strip().split(',')
                if len(parts) < 2:
                    continue
                corp_id = parts[0]
                company_name = parts[1]

                if corp_id in done:
                    continue

                domain, url, engine = search_domain(company_name)

                if domain:
                    domains_found += 1
                    with open(OUTPUT_TSV, 'a') as tf:
                        tf.write(f"{corp_id}\t{company_name}\t{domain}\t{url}\n")

                with open(DONE_FILE, 'a') as df:
                    df.write(f"{corp_id}\n")

                processed += 1
                if processed % 100 == 0:
                    ts = datetime.now().strftime('%H:%M:%S')
                    rate = domains_found/processed*100 if processed else 0
                    active_count = len([e for e in ENGINES if not engine_stats[e]['disabled']])
                    stats = ' | '.join([f"{e}:{engine_stats[e]['success']}/{engine_stats[e]['success']+engine_stats[e]['fail']}{'[停止]' if engine_stats[e]['disabled'] else ''}" for e in ENGINES])
                    msg = f"[{ts}] {processed}社 | ドメイン:{domains_found} ({rate:.1f}%) | 稼働:{active_count}/{len(ENGINES)} | {stats}"
                    print(msg)
                    log_engine(msg)

                time.sleep(random.uniform(5, 10))

    except KeyboardInterrupt:
        print(f"\n中断: {processed}社 | ドメイン: {domains_found}")

    log_engine(f"=== Step1終了 {processed}社 | ドメイン:{domains_found} ===")
    print(f"\n完了: {processed}社 | ドメイン: {domains_found}")

if __name__ == '__main__':
    main()
