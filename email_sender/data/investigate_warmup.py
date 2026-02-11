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

def investigate_warmup():
    print("=== 1. config.pyの全文表示 ===")
    success, content, error = run_command("cat /opt/libertycall/email_sender/config.py")
    if success:
        print(content)
    else:
        print(f"Error: {error}")
    
    print("\n=== 2. continuous_sender.pyの送信順序ロジック ===")
    # Look for recipient selection logic
    success, content, error = run_command("grep -A 20 -B 5 'select_recipients_for_today\\|load_recipients\\|送信対象\\|follow\\|initial' /opt/libertycall/email_sender/continuous_sender.py")
    if success:
        print(content)
    else:
        print("関連ロジックが見つかりませんでした")
    
    print("\n=== 3. ウォームアップスケジュール ===")
    # Search for warmup related logic
    search_patterns = [
        "daily_limit",
        "DAILY_SEND_LIMIT", 
        "warmup",
        "バウンス",
        "bounce",
        "段階",
        "増やす",
        "50",
        "200"
    ]
    
    for pattern in search_patterns:
        success, content, error = run_command(f"grep -n -i '{pattern}' /opt/libertycall/email_sender/continuous_sender.py")
        if success and content.strip():
            print(f"--- {pattern} 関連 ---")
            print(content)
    
    print("\n=== 4. csv_repository_prod.pyの送信対象抽出ロジック ===")
    # Get load_recipients function
    success, content, error = run_command("sed -n '/def load_recipients/,/^def /p' /opt/libertycall/email_sender/csv_repository_prod.py | head -50")
    if success:
        print("load_recipients() 関数:")
        print(content)
    
    # Also check select_recipients_for_today
    success, content, error = run_command("grep -A 30 'def select_recipients_for_today' /opt/libertycall/email_sender/scheduler_service_prod.py")
    if success:
        print("\nselect_recipients_for_today() 関数:")
        print(content)

if __name__ == "__main__":
    investigate_warmup()
