#!/usr/bin/env python3
import subprocess

def run_command(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def check_warmup_logic():
    print("=== 1. ウォームアップの上限管理 ===")
    
    # Search for 50 in continuous_sender.py
    success, content, error = run_command("grep -n '50' /opt/libertycall/email_sender/continuous_sender.py")
    if success:
        print("continuous_sender.py内の'50':")
        print(content)
    
    # Search for DAILY_SEND_LIMIT usage
    success, content, error = run_command("grep -rn 'DAILY_SEND_LIMIT' /opt/libertycall/email_sender/")
    if success:
        print("\nDAILY_SEND_LIMITの使用箇所:")
        print(content)
    
    print("\n=== 2. 自動増加ロジックの全文 ===")
    # Get full update_daily_limit_automatically function
    success, content, error = run_command("sed -n '/def update_daily_limit_automatically/,/^def /p' /opt/libertycall/email_sender/sendgrid_analytics.py")
    if success:
        print("update_daily_limit_automatically() 関数:")
        print(content)
    
    # Also get calculate_daily_limit function
    success, content, error = run_command("sed -n '/def calculate_daily_limit/,/^def /p' /opt/libertycall/email_sender/sendgrid_analytics.py")
    if success:
        print("\ncalculate_daily_limit() 関数:")
        print(content)
    
    print("\n=== 3. 上限の保存先 ===")
    # Find limit/warmup/state files
    success, content, error = run_command("find /opt/libertycall/ -name '*limit*' -o -name '*warmup*' -o -name '*state*' | head -20")
    if success and content.strip():
        print("見つかったファイル:")
        for file_path in content.strip().split('\n'):
            print(f"\n--- {file_path} ---")
            success, file_content, error = run_command(f"cat {file_path}")
            if success:
                print(file_content[:500])  # First 500 chars
            else:
                print("読み込みエラー")
    
    # Find JSON files
    success, content, error = run_command("find /opt/libertycall/ -name '*.json' | head -20")
    if success and content.strip():
        print("\nJSONファイル:")
        for file_path in content.strip().split('\n'):
            print(f"\n--- {file_path} ---")
            success, file_content, error = run_command(f"cat {file_path}")
            if success:
                print(file_content[:500])  # First 500 chars
            else:
                print("読み込みエラー")
    
    print("\n=== 4. continuous_sender.pyの起動時の上限取得 ===")
    # Find initialization code
    success, content, error = run_command("grep -A 10 -B 5 '初期送信上限\\|load_daily_limit\\daily_limit.*=' /opt/libertycall/email_sender/continuous_sender.py")
    if success:
        print("起動時の上限取得ロジック:")
        print(content)

if __name__ == "__main__":
    check_warmup_logic()
