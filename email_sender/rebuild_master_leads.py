#!/usr/bin/env python3
"""
master_leads.csv を業種別リストから再構築するスクリプト

使用方法:
    python3 email_sender/rebuild_master_leads.py
"""

import csv
import sys
from pathlib import Path
from typing import List, Dict, Set

# プロジェクトルートのパス
PROJECT_ROOT = Path(__file__).parent.parent
LIST_DIR = PROJECT_ROOT / "email_sender" / "list" / "豕穂ｺｺ蝟ｶ讌ｭ繝ｪ繧ｹ繝・(2)_csv"
OUTPUT_DIR = Path(__file__).parent / "data"
MASTER_LEADS_PATH = OUTPUT_DIR / "master_leads.csv"


def get_csv_files() -> List[Path]:
    """業種別リストのCSVファイルを取得"""
    if not LIST_DIR.exists():
        print(f"[ERROR] リストディレクトリが見つかりません: {LIST_DIR}")
        return []
    
    csv_files = list(LIST_DIR.glob("*.csv"))
    # __MACOSX ディレクトリ内のファイルを除外
    csv_files = [f for f in csv_files if "__MACOSX" not in str(f)]
    
    return sorted(csv_files)


def read_csv_file(csv_path: Path) -> List[Dict]:
    """CSVファイルを読み込む"""
    recipients = []
    
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            # まず1行目を読んでヘッダーを確認
            first_line = f.readline().strip()
            f.seek(0)  # ファイルポインタを先頭に戻す
            
            # カンマ区切りかタブ区切りかを判定
            if "\t" in first_line:
                reader = csv.DictReader(f, delimiter="\t")
            else:
                reader = csv.DictReader(f)
            
            for row in reader:
                # メールアドレスを取得（複数のカラム名に対応）
                email = (
                    row.get("email", "") or
                    row.get("E-Mail", "") or
                    row.get("E-mail", "") or
                    row.get("メールアドレス", "") or
                    row.get("Email", "") or
                    row.get("EMAIL", "") or
                    row.get("e-mail", "")
                ).strip()
                
                if not email or "@" not in email:
                    continue
                
                # 会社名を取得（「氏名」カラムが会社名の場合がある）
                company_name = (
                    row.get("company_name", "") or
                    row.get("会社名", "") or
                    row.get("Company Name", "") or
                    row.get("COMPANY_NAME", "") or
                    row.get("企業名", "") or
                    row.get("氏名", "") or
                    row.get("Name", "") or
                    row.get("name", "")
                ).strip()
                
                # 住所を取得
                address = (
                    row.get("address", "") or
                    row.get("住所", "") or
                    row.get("Address", "") or
                    row.get("ADDRESS", "")
                ).strip()
                
                # ステージ（デフォルト: initial）
                stage = (
                    row.get("stage", "") or
                    row.get("ステージ", "") or
                    row.get("Stage", "")
                ).strip() or "initial"
                
                recipient = {
                    "email": email.lower(),  # 小文字に統一
                    "company_name": company_name,
                    "address": address,
                    "stage": stage,
                    "last_sent_date": "",
                    "initial_sent_date": ""
                }
                
                recipients.append(recipient)
    
    except Exception as e:
        print(f"[WARN] {csv_path.name} の読み込みエラー: {e}")
        return []
    
    return recipients


def merge_recipients(all_recipients: List[Dict]) -> List[Dict]:
    """重複メールアドレスを統合（最新の情報を優先）"""
    email_dict: Dict[str, Dict] = {}
    
    for recipient in all_recipients:
        email = recipient["email"]
        
        # 既に存在する場合は、会社名や住所が空でない方を優先
        if email in email_dict:
            existing = email_dict[email]
            
            # 会社名が空の場合は更新
            if not existing["company_name"] and recipient["company_name"]:
                existing["company_name"] = recipient["company_name"]
            
            # 住所が空の場合は更新
            if not existing["address"] and recipient["address"]:
                existing["address"] = recipient["address"]
            
            # ステージが "initial" でない場合は更新
            if existing["stage"] == "initial" and recipient["stage"] != "initial":
                existing["stage"] = recipient["stage"]
        else:
            email_dict[email] = recipient.copy()
    
    return list(email_dict.values())


def main():
    """メイン処理"""
    print("=== master_leads.csv 再構築スクリプト ===\n")
    
    # CSVファイルを取得
    csv_files = get_csv_files()
    
    if not csv_files:
        print("[ERROR] CSVファイルが見つかりませんでした")
        return 1
    
    print(f"[INFO] {len(csv_files)} 個のCSVファイルを処理します\n")
    
    # すべてのレシピエントを読み込む
    all_recipients = []
    total_count = 0
    
    for csv_file in csv_files:
        recipients = read_csv_file(csv_file)
        count = len(recipients)
        total_count += count
        all_recipients.extend(recipients)
        print(f"[INFO] {csv_file.name}: {count} 件")
    
    print(f"\n[INFO] 合計: {total_count} 件（重複含む）")
    
    # 重複を統合
    print("\n[INFO] 重複メールアドレスを統合中...")
    merged_recipients = merge_recipients(all_recipients)
    unique_count = len(merged_recipients)
    duplicate_count = total_count - unique_count
    
    print(f"[INFO] 重複除外後: {unique_count} 件（{duplicate_count} 件の重複を除外）")
    
    # 出力ディレクトリを作成
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # master_leads.csv を書き込む
    print(f"\n[INFO] {MASTER_LEADS_PATH} に書き込み中...")
    
    fieldnames = ["email", "company_name", "address", "stage", "last_sent_date", "initial_sent_date"]
    
    try:
        with open(MASTER_LEADS_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(merged_recipients)
        
        print(f"[SUCCESS] master_leads.csv を作成しました: {unique_count} 件")
        print(f"[INFO] ファイルパス: {MASTER_LEADS_PATH}")
        
        # ファイルサイズを表示
        file_size = MASTER_LEADS_PATH.stat().st_size
        print(f"[INFO] ファイルサイズ: {file_size / 1024:.2f} KB")
        
        return 0
    
    except Exception as e:
        print(f"[ERROR] ファイル書き込みエラー: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

