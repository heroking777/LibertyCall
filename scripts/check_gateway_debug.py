#!/usr/bin/env python3
"""
Gateway デバッグログ確認スクリプト
- Gateway プロセス確認
- デバッグログの検索
- 無音検知ログの確認
"""
import subprocess
import sys
import os
from pathlib import Path

def run_cmd(cmd, shell=True):
    """コマンドを実行して結果を返す"""
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)

def main():
    print("=" * 60)
    print("Gateway デバッグログ確認")
    print("=" * 60)
    
    # 1. Gateway プロセス確認
    print("\n[1] Gateway プロセス確認")
    print("-" * 60)
    code, stdout, stderr = run_cmd("ps aux | grep gateway | grep -v grep")
    if code == 0 and stdout.strip():
        print(stdout)
    else:
        print("Gateway プロセスが見つかりませんでした")
    
    # 2. サービスの管理方式確認
    print("\n[2] サービスの管理方式確認")
    print("-" * 60)
    code, stdout, stderr = run_cmd("systemctl list-units --type=service | grep liberty")
    if code == 0 and stdout.strip():
        print("[INFO] Detected: systemd service")
        code2, stdout2, stderr2 = run_cmd("systemctl status service 2>&1 | head -10")
        if code2 == 0:
            print(stdout2)
    else:
        code3, stdout3, stderr3 = run_cmd("command -v supervisorctl")
        if code3 == 0:
            print("[INFO] Detected: supervisor managed")
        else:
            print("[WARN] No service manager detected")
    
    # 3. デバッグログの検索（journalctl）
    print("\n[3] journalctl からデバッグログ検索")
    print("-" * 60)
    keywords = ["DEBUG_INIT", "_start_no_input_timer", "_handle_no_input_timeout", 
                "on_audio_activity", "FORCE_HANGUP", "NO_INPUT"]
    
    for keyword in keywords:
        code, stdout, stderr = run_cmd(
            f"journalctl -u service --since '1 hour ago' --no-pager 2>&1 | grep '{keyword}' | tail -5"
        )
        if code == 0 and stdout.strip():
            print(f"\n[{keyword}]")
            print(stdout)
    
    # 4. conversation_trace.log から検索
    print("\n[4] conversation_trace.log から検索")
    print("-" * 60)
    trace_log = Path("/opt/libertycall/logs/conversation_trace.log")
    if trace_log.exists():
        try:
            with open(trace_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # 最後の50行を確認
                for line in lines[-50:]:
                    if any(kw in line for kw in keywords):
                        print(line.rstrip())
        except Exception as e:
            print(f"Error reading trace log: {e}")
    else:
        print("conversation_trace.log が見つかりません")
    
    # 5. log から検索（最新部分）
    print("\n[5] log から検索（最新500行）")
    print("-" * 60)
    log_file = Path("/var/log/log")
    if log_file.exists():
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                # 最後の500行を確認
                found = False
                for line in lines[-500:]:
                    if any(kw in line for kw in keywords):
                        print(line.rstrip())
                        found = True
                if not found:
                    print("デバッグログが見つかりませんでした（最新500行内）")
        except Exception as e:
            print(f"Error reading log: {e}")
    else:
        print("log が見つかりません")
    
    print("\n" + "=" * 60)
    print("確認完了")
    print("=" * 60)

if __name__ == "__main__":
    main()
