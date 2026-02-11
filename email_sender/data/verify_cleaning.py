#!/usr/bin/env python3
import csv
import re

def verify_cleaning(input_file):
    # Read CSV
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"Loaded {len(rows)} records from {input_file}")
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return
    
    modifications = False
    
    # 確認1：広報窓口の漏れチェック
    print("\n=== 確認1：広報窓口の漏れチェック ===")
    pr_patterns = ['press@', 'pr@', 'kouhou@', 'koho@']
    
    for row in rows:
        email = str(row.get('email', '')).strip().lower()
        if not email or email == 'nan':
            continue
            
        # Check for PR patterns
        for pattern in pr_patterns:
            if email.startswith(pattern):
                print(f"Found PR email: {email} - Current exclusion: {row.get('除外', '')}")
                if row.get('除外') != '広報窓口':
                    print(f"  -> 修正: '広報窓口' に変更")
                    row['除外'] = '広報窓口'
                    modifications = True
                break
    
    # 確認2：IR窓口の漏れチェック
    print("\n=== 確認2：IR窓口の漏れチェック ===")
    
    for row in rows:
        email = str(row.get('email', '')).strip().lower()
        if not email or email == 'nan':
            continue
            
        if email.startswith('ir@'):
            print(f"Found IR email: {email} - Current exclusion: {row.get('除外', '')}")
            if row.get('除外') != 'IR窓口':
                print(f"  -> 修正: 'IR窓口' に変更")
                row['除外'] = 'IR窓口'
                modifications = True
    
    # 確認3：アドレス不正の漏れチェック
    print("\n=== 確認3：アドレス不正の漏れチェック ===")
    
    for row in rows:
        email = str(row.get('email', '')).strip().lower()
        if not email or email == 'nan':
            continue
            
        # Check for .cojp (no dot)
        if '.cojp' in email:
            print(f"Found .cojp email: {email} - Current exclusion: {row.get('除外', '')}")
            if row.get('除外') != 'アドレス不正':
                print(f"  -> 修正: 'アドレス不正' に変更")
                row['除外'] = 'アドレス不正'
                modifications = True
        
        # Check for spaces
        elif ' @' in email or '@ ' in email or email.count('@') != 1:
            print(f"Found email with space issues: {email} - Current exclusion: {row.get('除外', '')}")
            if row.get('除外') != 'アドレス不正':
                print(f"  -> 修正: 'アドレス不正' に変更")
                row['除外'] = 'アドレス不正'
                modifications = True
    
    # Save if modifications were made
    if modifications:
        try:
            with open(input_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"\n修正を保存しました: {input_file}")
        except Exception as e:
            print(f"Error saving CSV: {e}")
            return
    else:
        print("\n修正なし")
    
    # Print updated summary
    exclusion_counts = {
        'アドレス不正': 0,
        '採用窓口': 0,
        'IR窓口': 0,
        '広報窓口': 0
    }
    
    for row in rows:
        exclusion = row.get('除外', '')
        if exclusion in exclusion_counts:
            exclusion_counts[exclusion] += 1
    
    total_count = len(rows)
    total_excluded = sum(exclusion_counts.values())
    remaining_count = total_count - total_excluded
    
    print("\n=== 修正後の除外件数サマリ ===")
    print(f"全件数: {total_count}")
    print(f"除外件数: {total_excluded}")
    for reason, count in exclusion_counts.items():
        print(f"  - {reason}: {count}")
    print(f"残った件数: {remaining_count}")

if __name__ == "__main__":
    input_file = "/opt/libertycall/email_sender/data/cleaned_list.csv"
    verify_cleaning(input_file)
