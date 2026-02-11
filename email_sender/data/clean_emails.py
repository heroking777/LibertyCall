#!/usr/bin/env python3
import pandas as pd
import re
import sys

def clean_emails(input_file, output_file):
    # Read CSV
    try:
        df = pd.read_csv(input_file)
        print(f"Loaded {len(df)} records from {input_file}")
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return
    
    # Initialize exclusion column
    df['除外'] = ''
    
    exclusion_counts = {
        'アドレス不正': 0,
        '採用窓口': 0,
        'IR窓口': 0,
        '広報窓口': 0
    }
    
    for idx, row in df.iterrows():
        email = str(row['email']).strip().lower()
        
        # Skip if email is empty or NaN
        if pd.isna(row['email']) or email == 'nan':
            continue
            
        # Check condition 1: Address invalid
        exclusion_reason = None
        
        # Check for .co.jp vs .cojp
        if '.cojp' in email:
            exclusion_reason = 'アドレス不正'
        # Check for spaces around @
        elif ' @' in email or '@ ' in email or email.count('@') != 1:
            exclusion_reason = 'アドレス不正'
        # Check for obvious domain typos (missing dots)
        elif re.match(r'.*@[^.]+\.[^.]+$', email) and '.' not in email.split('@')[1]:
            exclusion_reason = 'アドレス不正'
        
        # If not excluded for address issues, check other conditions
        if exclusion_reason is None:
            local_part = email.split('@')[0]
            
            # Check condition 2: Recruitment addresses
            if (re.search(r'saiyo', local_part) or 
                re.search(r'recruit', local_part) or
                re.search(r'jinji', local_part) or
                local_part.startswith('hr@') or
                re.search(r'shinsotsu', local_part) or
                re.search(r'fresh', local_part) or
                re.search(r'career', local_part)):
                exclusion_reason = '採用窓口'
            
            # Check condition 3: IR addresses
            elif local_part.startswith('ir@'):
                exclusion_reason = 'IR窓口'
            
            # Check condition 4: PR addresses
            elif (local_part.startswith('press@') or
                  local_part.startswith('pr@') or
                  local_part.startswith('kouhou@') or
                  local_part.startswith('koho@')):
                exclusion_reason = '広報窓口'
        
        # Set exclusion reason if found
        if exclusion_reason:
            df.at[idx, '除外'] = exclusion_reason
            exclusion_counts[exclusion_reason] += 1
    
    # Save cleaned CSV
    try:
        df.to_csv(output_file, index=False, encoding='utf-8')
        print(f"Saved cleaned data to {output_file}")
    except Exception as e:
        print(f"Error saving CSV: {e}")
        return
    
    # Print summary
    total_count = len(df)
    total_excluded = sum(exclusion_counts.values())
    remaining_count = total_count - total_excluded
    
    print("\n=== サマリ ===")
    print(f"全件数: {total_count}")
    print(f"除外件数: {total_excluded}")
    for reason, count in exclusion_counts.items():
        if count > 0:
            print(f"  - {reason}: {count}")
    print(f"残った件数: {remaining_count}")

if __name__ == "__main__":
    input_file = "/opt/libertycall/email_sender/data/master_leads.csv"
    output_file = "/opt/libertycall/email_sender/data/cleaned_list.csv"
    
    clean_emails(input_file, output_file)
