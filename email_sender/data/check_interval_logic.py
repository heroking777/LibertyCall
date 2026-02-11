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

def check_interval_logic():
    print("=== continuous_sender.py の送信間隔ロジック ===")
    
    # Search for interval/sleep related code
    search_patterns = [
        "sleep",
        "interval", 
        "random",
        "time.sleep",
        "calculate_random_interval",
        "次の送信まで",
        "待機"
    ]
    
    for pattern in search_patterns:
        success, content, error = run_command(f"grep -n -A 5 -B 5 '{pattern}' /opt/libertycall/email_sender/continuous_sender.py")
        if success and content.strip():
            print(f"\n--- {pattern} 関連 ---")
            print(content)
    
    # Also look for the calculate_random_interval function specifically
    success, content, error = run_command("grep -A 20 'def calculate_random_interval' /opt/libertycall/email_sender/continuous_sender.py")
    if success:
        print(f"\n--- calculate_random_interval 関数全文 ---")
        print(content)

if __name__ == "__main__":
    check_interval_logic()
