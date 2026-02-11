#!/usr/bin/env python3
import subprocess
import os
import glob

def run_command(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def check_system_config():
    print("=== 1. デーモンの設定確認 ===")
    
    # Check systemd service file
    service_file = "/etc/systemd/system/continuous_sender.service"
    success, output, error = run_command(f"cat {service_file}")
    if success:
        print(f"continuous_sender.serviceの内容:")
        print(output)
    else:
        print(f"サービスファイルが見つかりません: {service_file}")
        # Try to find similar service files
        success, output, error = run_command("find /etc/systemd/system -name '*sender*' -o -name '*mail*' -o -name '*email*'")
        if success and output.strip():
            print(f"関連するサービスファイル:")
            print(output)
    
    print("\n=== 2. 送信スクリプトの確認 ===")
    
    # Look for sender scripts
    script_paths = [
        "/opt/libertycall/email_sender/sender.py",
        "/opt/libertycall/email_sender/continuous_sender.py",
        "/opt/libertycall/sender.py",
        "/opt/continuous_sender.py"
    ]
    
    for script_path in script_paths:
        if os.path.exists(script_path):
            print(f"送信スクリプトを発見: {script_path}")
            success, content, error = run_command(f"cat {script_path}")
            if success:
                print(f"スクリプト内容:")
                print(content)
            break
    else:
        # Search for sender scripts
        success, output, error = run_command("find /opt -name '*sender*' -type f 2>/dev/null")
        if success and output.strip():
            print(f"見つかったsender関連ファイル:")
            for line in output.strip().split('\n'):
                if line.endswith('.py'):
                    print(f"  {line}")
                    success, content, error = run_command(f"head -50 {line}")
                    if success:
                        print(f"    先頭50行:")
                        print(content)
                        print("    ---")
    
    print("\n=== 3. CSVファイルの状態確認 ===")
    
    # Check various CSV paths
    csv_paths = [
        "/opt/libertycall/email_sender/data/master_leads.csv",
        "/opt/libertycall/email_sender/data/cleaned_list.csv",
        "/opt/libertycall/master_leads.csv",
        "/opt/master_leads.csv"
    ]
    
    for csv_path in csv_paths:
        if os.path.exists(csv_path):
            print(f"\nCSVファイル: {csv_path}")
            # Get header
            success, header, error = run_command(f"head -1 {csv_path}")
            if success:
                print(f"ヘッダー: {header.strip()}")
            
            # Get line count
            success, count, error = run_command(f"wc -l {csv_path}")
            if success:
                print(f"総行数: {count.strip()}")
    
    print("\n=== 4. list_cleanerの確認 ===")
    
    # Check for cleaner scripts
    cleaner_paths = [
        "/opt/libertycall/email_sender/list_cleaner.py",
        "/opt/libertycall/list_cleaner.py",
        "/opt/list_cleaner.py"
    ]
    
    for cleaner_path in cleaner_paths:
        if os.path.exists(cleaner_path):
            print(f"list_cleanerを発見: {cleaner_path}")
            success, content, error = run_command(f"cat {cleaner_path}")
            if success:
                print(f"スクリプト内容:")
                print(content)
            break
    
    # Check crontab
    success, crontab, error = run_command("crontab -l")
    if success:
        print(f"\ncrontab設定:")
        print(crontab)
    else:
        print(f"\ncrontab設定なし、または取得エラー: {error}")
    
    print("\n=== 5. ウォームアップ設定の確認 ===")
    
    # Search for warmup related code
    search_dirs = ["/opt/libertycall/email_sender", "/opt/libertycall", "/opt"]
    for search_dir in search_dirs:
        if os.path.exists(search_dir):
            success, output, error = run_command(f"grep -r -i \"warmup\\|limit\\|bounce\\|rate\" {search_dir} --include=\"*.py\" 2>/dev/null | head -20")
            if success and output.strip():
                print(f"ウォームアップ関連コード ({search_dir}):")
                print(output)
                break

if __name__ == "__main__":
    check_system_config()
