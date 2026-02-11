#!/usr/bin/env python3
import subprocess
import os

def run_command(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def check_facts():
    print("=== 1. 現在のDAILY_SEND_LIMITの実際の値 ===")
    
    # config.py全文
    success, content, error = run_command("cat /opt/libertycall/email_sender/config.py")
    if success:
        print("config.py全文:")
        print(content)
    else:
        print(f"config.py読み込みエラー: {error}")
    
    # 環境変数確認
    print("\n環境変数 DAILY_SEND_LIMIT:")
    success, content, error = run_command("echo $DAILY_SEND_LIMIT")
    if success:
        print(f"DAILY_SEND_LIMIT={content.strip()}")
    else:
        print("未設定")
    
    success, content, error = run_command("printenv | grep DAILY")
    if success and content.strip():
        print("DAILY関連の環境変数:")
        print(content)
    else:
        print("DAILY関連の環境変数なし")
    
    print("\n=== 2. デーモンの稼働状況 ===")
    success, content, error = run_command("systemctl status continuous_sender")
    if success:
        print(content)
    else:
        print(f"ステータス取得エラー: {error}")
    
    print("\n=== 3. 実際の送信ログ ===")
    success, content, error = run_command("sudo journalctl -u continuous_sender --no-pager | tail -100")
    if success:
        print(content)
    else:
        print(f"ジャーナルログ取得エラー: {error}")
    
    print("\n=== 4. SendGrid送信ログ ===")
    # Find log files
    success, content, error = run_command("find /opt/libertycall/ -name '*.log' -type f")
    if success and content.strip():
        print("見つかったログファイル:")
        for log_file in content.strip().split('\n'):
            print(f"\n--- {log_file} ---")
            success, log_content, error = run_command(f"tail -50 {log_file}")
            if success:
                print(log_content)
            else:
                print(f"読み込みエラー: {error}")
    else:
        print("ログファイルなし")
    
    # Find log files with 'log' in name
    success, content, error = run_command("find /opt/libertycall/ -name '*log*' -type f")
    if success and content.strip():
        print("\nlogを含むファイル:")
        print(content)
    
    print("\n=== 5. master_leads.csvの送信済み件数 ===")
    
    # Count stages
    stages = ["initial", "follow1", "follow2", "follow3", "completed"]
    for stage in stages:
        success, count, error = run_command(f"grep -c ',{stage},' /opt/libertycall/email_sender/data/master_leads.csv")
        if success:
            print(f"stage={stage}: {count.strip()}件")
        else:
            print(f"stage={stage}: カウントエラー")
    
    # Count non-empty last_sent_date
    success, count, error = run_command("grep -v ',,$' /opt/libertycall/email_sender/data/master_leads.csv | grep -v ',last_sent_date,' | grep -c ','")
    if success:
        print(f"last_sent_dateが空でない件数: {count.strip()}件")
    else:
        # Alternative method
        success, count, error = run_command("awk -F',' 'NR>1 && $5!=\"\" {print}' /opt/libertycall/email_sender/data/master_leads.csv | wc -l")
        if success:
            print(f"last_sent_dateが空でない件数: {count.strip()}件")
        else:
            print("last_sent_dateカウントエラー")

if __name__ == "__main__":
    check_facts()
