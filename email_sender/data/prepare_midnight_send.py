#!/usr/bin/env python3
import subprocess
import csv
import json

def run_command(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def prepare_midnight_send():
    print("=== 作業1：デーモン停止 ===")
    
    # Stop daemon
    success, output, error = run_command("sudo systemctl stop continuous_sender")
    if success:
        print("デーモン停止完了")
    else:
        print(f"停止エラー: {error}")
    
    # Check status
    success, output, error = run_command("sudo systemctl status continuous_sender")
    if success:
        print("デーモンステータス:")
        print(output)
    
    print("\n=== 作業2：master_leads.csvのバックアップと差し替え ===")
    
    # Change directory
    import os
    os.chdir("/opt/libertycall/email_sender/data")
    
    # Backup
    success, output, error = run_command("cp master_leads.csv master_leads_backup_20260208.csv")
    if success:
        print("バックアップ完了")
    else:
        print(f"バックアップエラー: {error}")
    
    # Filter cleaned_list.csv (exclude rows with non-empty 除外 column)
    filtered_rows = []
    with open("cleaned_list.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        # Remove 除外 column from fieldnames
        new_fieldnames = [field for field in fieldnames if field != "除外"]
        
        for row in reader:
            if row.get("除外", "") == "":  # Only keep rows with empty 除外
                # Remove 除外 column from row
                new_row = {key: value for key, value in row.items() if key != "除外"}
                filtered_rows.append(new_row)
    
    # Write to master_leads.csv
    with open("master_leads.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)
    
    print(f"フィルタリング完了: {len(filtered_rows)}件を保存")
    
    # Verify
    success, count, error = run_command("wc -l /opt/libertycall/email_sender/data/master_leads.csv")
    if success:
        print(f"行数: {count.strip()}")
    
    success, header, error = run_command("head -1 /opt/libertycall/email_sender/data/master_leads.csv")
    if success:
        print(f"ヘッダー: {header.strip()}")
    
    success, rows, error = run_command("head -5 /opt/libertycall/email_sender/data/master_leads.csv")
    if success:
        print("先頭5行:")
        print(rows)
    
    print("\n=== 作業3：daily_limit.jsonをリセット ===")
    
    # Reset daily_limit.json
    limit_data = {
        "date": "2026-02-09",
        "daily_limit": 50,
        "updated_at": "2026-02-09T00:00:00"
    }
    
    with open("/opt/libertycall/email_sender/daily_limit.json", "w", encoding="utf-8") as f:
        json.dump(limit_data, f, indent=2, ensure_ascii=False)
    
    print("daily_limit.jsonをリセット")
    
    # Verify
    success, content, error = run_command("cat /opt/libertycall/email_sender/daily_limit.json")
    if success:
        print("内容:")
        print(content)
    
    print("\n=== 作業4：0:00に自動起動するcronを設定 ===")
    
    # Add cron job
    cron_cmd = "0 0 * * * sudo systemctl start continuous_sender"
    
    # Check current crontab
    success, current_cron, error = run_command("crontab -l")
    if not success and "no crontab" in error:
        current_cron = ""
    
    # Add new cron job
    new_cron = current_cron.strip() + "\n" + cron_cmd + "\n"
    
    # Write new crontab
    success, output, error = run_command(f"echo '{new_cron}' | crontab -")
    if success:
        print("cron設定完了")
    else:
        print(f"cron設定エラー: {error}")
    
    # Verify cron
    success, output, error = run_command("crontab -l")
    if success:
        print("現在のcron設定:")
        print(output)
    
    print("\n=== 作業5：最終確認 ===")
    
    # Final checks
    checks = [
        ("デーモンステータス", "sudo systemctl status continuous_sender"),
        ("daily_limit.json", "cat /opt/libertycall/email_sender/daily_limit.json"),
        ("master_leads.csv行数", "wc -l /opt/libertycall/email_sender/data/master_leads.csv"),
        ("cron設定", "crontab -l")
    ]
    
    for name, cmd in checks:
        print(f"\n--- {name} ---")
        success, output, error = run_command(cmd)
        if success:
            print(output)
        else:
            print(f"エラー: {error}")

if __name__ == "__main__":
    prepare_midnight_send()
