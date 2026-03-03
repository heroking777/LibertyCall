import json, sys, subprocess, time

domains = set()
for c in 'abcdefghijklmnopqrstuvwxyz0123456789':
    q = f"{c}%.co.jp"
    print(f"Fetching {q}...", file=sys.stderr)
    try:
        r = subprocess.run(['curl', '-s', f'https://crt.sh/?q={q}&output=json'], capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout)
        for e in data:
            for f in ['common_name', 'name_value']:
                v = e.get(f) or ''
                for n in v.split('\n'):
                    n = n.strip().lstrip('*.')
                    if n.endswith('.co.jp'):
                        parts = n.split('.')
                        try:
                            i = parts.index('co')
                            root = '.'.join(parts[i-1:])
                            domains.add(root)
                        except:
                            pass
    except:
        pass
    time.sleep(5)

with open('/opt/libertycall/scraper/data/cojp_domains_full.txt', 'w') as f:
    for d in sorted(domains):
        f.write(d + '\n')
print(f"Done: {len(domains)} domains", file=sys.stderr)
