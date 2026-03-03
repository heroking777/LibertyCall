"""
並列スクレイパー実行スクリプト
各カテゴリを別プロセスで同時実行、ログはカテゴリ別ファイルに出力
"""
import subprocess
import sys
import time
import os

PYTHON = '/opt/libertycall/scraper/venv/bin/python'
EKITEN = '/opt/libertycall/scraper/sites/ekiten.py'

CATEGORIES = [
    ('clinic', 100),
    ('life', 100),
    ('food', 100),
    ('store', 100),
    ('relax', 100),
    ('beauty', 100),
    ('school', 50),
    ('lesson', 50),
]

def main():
    max_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    procs = []

    for cat, pages in CATEGORIES[:max_workers]:
        log_file = f'/opt/libertycall/scraper/logs/ekiten_{cat}.log'
        print(f"Starting {cat} (max {pages} pages) -> {log_file}")
        proc = subprocess.Popen(
            [PYTHON, EKITEN, cat, str(pages)],
        )
        procs.append((cat, proc))
        time.sleep(3)

    print(f"\n{len(procs)} workers running.")
    print(f"Monitor with: tail -f /opt/libertycall/scraper/logs/ekiten_*.log")
    print(f"Stop with: pkill -f ekiten.py\n")

    while procs:
        for cat, proc in procs[:]:
            ret = proc.poll()
            if ret is not None:
                print(f"[DONE] {cat}: exit code {ret}")
                procs.remove((cat, proc))
        time.sleep(60)

    print("\nAll workers finished.")

if __name__ == '__main__':
    main()
