#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
メールリスト簡易バリデーションツール
master_leads.csvのメールアドレスを検証します
"""

import csv
import re
import socket
from pathlib import Path
from tqdm import tqdm

# ==============================
# メール形式チェック（正規表現）
# ==============================
def is_valid_format(email):
    """メールアドレスの形式が正しいかチェック"""
    if not email or not email.strip():
        return False
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return bool(re.match(pattern, email.strip()))


# ==============================
# SMTPでドメイン生存チェック（簡易）
# ==============================
def domain_alive(email):
    """ドメインが存在するかチェック（DNS解決）"""
    try:
        domain = email.split("@")[1]
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


# ==============================
# メイン処理
# ==============================
def main():
    print("=== メールリスト簡易バリデーションツール ===")
    print("master_leads.csvのメールアドレスを検証します\n")
    
    # デフォルトのパス
    default_input = "corp_collector/data/output/master_leads.csv"
    default_output = "corp_collector/data/output/master_leads_validated.csv"
    
    input_file = input(f"入力CSVファイル名を指定してください（デフォルト: {default_input}）: ").strip()
    if not input_file:
        input_file = default_input
    
    output_file = input(f"出力CSVファイル名を指定してください（デフォルト: {default_output}）: ").strip()
    if not output_file:
        output_file = default_output
    
    # ファイルの存在確認
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ エラー: ファイルが見つかりません: {input_file}")
        return
    
    # メールアドレスを読み込む
    emails = []
    records = []
    
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "email" not in reader.fieldnames:
            print("❌ エラー: CSVに 'email' カラムがありません。")
            return
        
        for row in reader:
            email = row.get("email", "").strip()
            if email:
                emails.append(email)
                records.append(row)
    
    print(f"\n→ {len(emails)}件のメールアドレスを検証中...\n")
    
    valid_list = []
    invalid_list = []
    
    # メールアドレスを検証
    for i, email in enumerate(tqdm(emails, desc="検証進行中")):
        record = records[i]
        status = "OK"
        reason = ""
        
        # 形式チェック
        if not is_valid_format(email):
            status = "Invalid format"
            reason = "形式が不正"
            invalid_list.append({
                "email": email,
                "company_name": record.get("company_name", ""),
                "address": record.get("address", ""),
                "stage": record.get("stage", ""),
                "status": status,
                "reason": reason
            })
            continue
        
        # ドメイン生存チェック
        if not domain_alive(email):
            status = "Domain not found"
            reason = "ドメインが見つからない"
            invalid_list.append({
                "email": email,
                "company_name": record.get("company_name", ""),
                "address": record.get("address", ""),
                "stage": record.get("stage", ""),
                "status": status,
                "reason": reason
            })
            continue
        
        # 有効なメールアドレス
        valid_list.append({
            "email": email,
            "company_name": record.get("company_name", ""),
            "address": record.get("address", ""),
            "stage": record.get("stage", ""),
            "status": status,
            "reason": reason
        })
    
    print(f"\n✅ 有効アドレス: {len(valid_list)} 件")
    print(f"⚠️ 無効アドレス: {len(invalid_list)} 件\n")
    
    # 結果をCSVに保存
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["email", "company_name", "address", "stage", "status", "reason"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # 有効なものから書き込み
        for record in valid_list:
            writer.writerow(record)
        
        # 無効なものを書き込み
        for record in invalid_list:
            writer.writerow(record)
    
    print(f"💾 結果を {output_file} に保存しました。")
    
    # 無効なメールアドレスの詳細を表示（最初の10件）
    if invalid_list:
        print(f"\n=== 無効なメールアドレス（最初の10件） ===")
        for i, record in enumerate(invalid_list[:10], 1):
            print(f"{i}. {record['email']} - {record['status']} ({record['reason']})")
            print(f"   会社名: {record['company_name']}")
        if len(invalid_list) > 10:
            print(f"\n... 他 {len(invalid_list) - 10}件")


if __name__ == "__main__":
    main()

