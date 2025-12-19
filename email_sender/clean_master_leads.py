#!/usr/bin/env python3
"""
master_leads.csv から重複ドメインと無効なメールアドレスを除外するスクリプト

使用方法:
    python3 email_sender/clean_master_leads.py [--backup]
"""

import csv
import sys
import re
import argparse
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict

# プロジェクトルートのパス
PROJECT_ROOT = Path(__file__).parent.parent
MASTER_LEADS_PATH = PROJECT_ROOT / "corp_collector" / "data" / "output" / "master_leads.csv"
BACKUP_PATH = PROJECT_ROOT / "corp_collector" / "data" / "output" / "master_leads.csv.backup"

# 無効なメールアドレスのパターン
INVALID_EMAIL_PATTERNS = [
    r"^test@",  # test@で始まる
    r"@test\.",  # @test.を含む
    r"^example@",  # example@で始まる
    r"@example\.",  # @example.を含む
    r"^noreply@",  # noreply@で始まる
    r"^no-reply@",  # no-reply@で始まる
    r"^donotreply@",  # donotreply@で始まる
    r"^mailer-daemon@",  # mailer-daemon@で始まる
    r"^postmaster@",  # postmaster@で始まる
    r"^abuse@",  # abuse@で始まる
    r"^webmaster@",  # webmaster@で始まる
    r"^info@info\.",  # info@info.を含む
    r"^admin@admin\.",  # admin@admin.を含む
]

# 無効なドメイン
INVALID_DOMAINS = {
    "test.com",
    "test.co.jp",
    "example.com",
    "example.co.jp",
    "sample.com",
    "sample.co.jp",
    "localhost",
    "invalid.com",
    "invalid.co.jp",
}


def is_valid_email_format(email: str) -> bool:
    """メールアドレスの形式が正しいかチェック"""
    if not email or "@" not in email:
        return False
    
    # 基本的な形式チェック
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False
    
    # 無効なパターンをチェック
    email_lower = email.lower()
    for pattern in INVALID_EMAIL_PATTERNS:
        if re.search(pattern, email_lower):
            return False
    
    # ドメイン部分を抽出
    domain = email.split("@")[1].lower()
    
    # 無効なドメインをチェック
    if domain in INVALID_DOMAINS:
        return False
    
    # ドメインが短すぎる場合は無効（例: a@b.c）
    if len(domain) < 4:
        return False
    
    return True


def extract_domain(email: str) -> str:
    """メールアドレスからドメインを抽出"""
    if "@" not in email:
        return ""
    return email.split("@")[1].lower()


def load_recipients() -> List[Dict]:
    """master_leads.csvを読み込む"""
    recipients = []
    
    if not MASTER_LEADS_PATH.exists():
        print(f"[ERROR] ファイルが見つかりません: {MASTER_LEADS_PATH}")
        return recipients
    
    try:
        with open(MASTER_LEADS_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                recipients.append(row)
    except Exception as e:
        print(f"[ERROR] ファイル読み込みエラー: {e}")
        return recipients
    
    return recipients


def clean_recipients(recipients: List[Dict], remove_duplicate_domains: bool = True) -> tuple[List[Dict], Dict[str, int]]:
    """
    レシピエントをクリーンアップ
    
    Args:
        recipients: レシピエントリスト
        remove_duplicate_domains: 重複ドメインを除外するか（True: 除外、False: 1つだけ残す）
    
    Returns:
        (クリーンアップ後のリスト, 統計情報)
    """
    stats = {
        "total": len(recipients),
        "invalid_format": 0,
        "duplicate_domain": 0,
        "duplicate_email": 0,
        "valid": 0
    }
    
    # メールアドレスで重複チェック
    seen_emails: Set[str] = set()
    email_to_recipient: Dict[str, Dict] = {}
    
    # ドメインごとのカウント
    domain_count: Dict[str, int] = defaultdict(int)
    domain_to_recipients: Dict[str, List[Dict]] = defaultdict(list)
    
    # 最初のパス: 形式チェックと重複メールアドレス除外
    valid_recipients = []
    
    for recipient in recipients:
        email = recipient.get("email", "").strip().lower()
        
        if not email:
            continue
        
        # 重複メールアドレスを除外
        if email in seen_emails:
            stats["duplicate_email"] += 1
            continue
        
        seen_emails.add(email)
        
        # 形式チェック
        if not is_valid_email_format(email):
            stats["invalid_format"] += 1
            continue
        
        # ドメインを記録
        domain = extract_domain(email)
        if domain:
            domain_count[domain] += 1
            domain_to_recipients[domain].append(recipient)
        
        email_to_recipient[email] = recipient
        valid_recipients.append(recipient)
    
    # 2番目のパス: 重複ドメインの処理
    cleaned_recipients = []
    
    if remove_duplicate_domains:
        # 重複ドメインを完全に除外
        for recipient in valid_recipients:
            email = recipient.get("email", "").strip().lower()
            domain = extract_domain(email)
            
            if domain_count[domain] > 1:
                stats["duplicate_domain"] += 1
                continue
            
            cleaned_recipients.append(recipient)
            stats["valid"] += 1
    else:
        # 重複ドメインから1つだけ残す（最初の1つ）
        seen_domains: Set[str] = set()
        
        for recipient in valid_recipients:
            email = recipient.get("email", "").strip().lower()
            domain = extract_domain(email)
            
            if domain in seen_domains:
                stats["duplicate_domain"] += 1
                continue
            
            if domain_count[domain] > 1:
                seen_domains.add(domain)
            
            cleaned_recipients.append(recipient)
            stats["valid"] += 1
    
    return cleaned_recipients, stats


def save_recipients(recipients: List[Dict], create_backup: bool = True):
    """レシピエントを保存"""
    # バックアップを作成
    if create_backup and MASTER_LEADS_PATH.exists():
        import shutil
        shutil.copy2(MASTER_LEADS_PATH, BACKUP_PATH)
        print(f"[INFO] バックアップを作成しました: {BACKUP_PATH}")
    
    # 保存
    fieldnames = ["email", "company_name", "address", "stage", "last_sent_date", "initial_sent_date"]
    
    try:
        with open(MASTER_LEADS_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(recipients)
        
        print(f"[SUCCESS] master_leads.csv を更新しました: {len(recipients)} 件")
    except Exception as e:
        print(f"[ERROR] ファイル書き込みエラー: {e}")
        raise


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description="master_leads.csv をクリーンアップ")
    parser.add_argument(
        "--keep-one-per-domain",
        action="store_true",
        help="重複ドメインから1つだけ残す（デフォルト: 重複ドメインを完全に除外）"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="バックアップを作成しない"
    )
    args = parser.parse_args()
    
    print("=== master_leads.csv クリーンアップスクリプト ===\n")
    
    # レシピエントを読み込む
    print("[INFO] master_leads.csv を読み込み中...")
    recipients = load_recipients()
    
    if not recipients:
        print("[ERROR] レシピエントが見つかりませんでした")
        return 1
    
    print(f"[INFO] 読み込み完了: {len(recipients)} 件\n")
    
    # クリーンアップ
    print("[INFO] クリーンアップ処理中...")
    remove_duplicate_domains = not args.keep_one_per_domain
    cleaned_recipients, stats = clean_recipients(recipients, remove_duplicate_domains)
    
    # 統計を表示
    print("\n=== クリーンアップ結果 ===")
    print(f"元の件数: {stats['total']:,} 件")
    print(f"無効な形式: {stats['invalid_format']:,} 件")
    print(f"重複メールアドレス: {stats['duplicate_email']:,} 件")
    print(f"重複ドメイン: {stats['duplicate_domain']:,} 件")
    print(f"有効な件数: {stats['valid']:,} 件")
    print(f"除外率: {(stats['total'] - stats['valid']) / stats['total'] * 100:.2f}%")
    
    # 保存
    print(f"\n[INFO] クリーンアップ後のファイルを保存中...")
    save_recipients(cleaned_recipients, create_backup=not args.no_backup)
    
    # ファイルサイズを表示
    file_size = MASTER_LEADS_PATH.stat().st_size
    print(f"[INFO] ファイルサイズ: {file_size / 1024:.2f} KB")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

