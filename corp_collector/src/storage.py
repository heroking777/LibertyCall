"""データ保存モジュール"""

import csv
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Tuple

logger = logging.getLogger("corp_collector.storage")

# 履歴ファイルのパス
HISTORY_PATH = Path("data/history/seen.csv")
# 実行ロックファイルのパス（1日1回実行を保証）
LOCK_PATH = Path("data/state/last_run_date.txt")


def save_records_to_csv(
    records: List[Dict[str, str]],
    output_dir: str,
    filename_prefix: str = "leads",
) -> str:
    """
    CSVファイルにレコードを保存する
    
    Args:
        records: 保存するレコードのリスト
        output_dir: 出力ディレクトリ
        filename_prefix: ファイル名のプレフィックス
        
    Returns:
        保存されたファイルのパス
    """
    # ディレクトリを作成
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # ファイル名を生成
    today = datetime.now().strftime("%Y%m%d")
    filename = f"{filename_prefix}_{today}.csv"
    filepath = Path(output_dir) / filename
    
    # カラム順を定義（メアド、会社名、住所のみ）
    fieldnames = [
        "email",
        "company_name",
        "address",
    ]
    
    # ファイルが存在するかチェック
    file_exists = filepath.exists()
    
    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 新規ファイルの場合はヘッダーを書き込む
            if not file_exists:
                writer.writeheader()
            
            # レコードを書き込む（必要なカラムのみ抽出）
            for record in records:
                filtered_record = {
                    "email": record.get("email", ""),
                    "company_name": record.get("company_name", ""),
                    "address": record.get("address", ""),
                }
                writer.writerow(filtered_record)
        
        logger.info(f"{len(records)} 件のレコードをCSVに保存: {filepath}")
        return str(filepath)
        
    except Exception as e:
        logger.error(f"CSV保存中にエラーが発生: {e}", exc_info=True)
        raise


def save_records_to_sqlite(
    records: List[Dict[str, str]],
    output_dir: str,
    filename_prefix: str = "leads",
) -> str:
    """
    SQLiteデータベースにレコードを保存する
    
    Args:
        records: 保存するレコードのリスト
        output_dir: 出力ディレクトリ
        filename_prefix: ファイル名のプレフィックス
        
    Returns:
        保存されたデータベースファイルのパス
    """
    # ディレクトリを作成
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # ファイル名を生成
    today = datetime.now().strftime("%Y%m%d")
    filename = f"{filename_prefix}_{today}.db"
    filepath = Path(output_dir) / filename
    
    try:
        conn = sqlite3.connect(filepath)
        cursor = conn.cursor()
        
        # テーブルを作成（存在しない場合）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                company_name TEXT,
                address TEXT,
                website_url TEXT,
                industry TEXT,
                domain TEXT,
                source TEXT,
                created_at TEXT,
                UNIQUE(email, domain)
            )
            """
        )
        
        # インデックスを作成
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email ON leads(email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_domain ON leads(domain)")
        
        # レコードを挿入
        inserted_count = 0
        for record in records:
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO leads 
                    (email, company_name, address, website_url, industry, domain, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.get("email", ""),
                        record.get("company_name", ""),
                        record.get("address", ""),
                        record.get("website_url", ""),
                        record.get("industry", ""),
                        record.get("domain", ""),
                        record.get("source", ""),
                        record.get("created_at", ""),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted_count += 1
            except sqlite3.Error as e:
                logger.warning(f"レコードの挿入中にエラー: {e}")
        
        conn.commit()
        conn.close()
        
        logger.info(f"{inserted_count} 件のレコードをSQLiteに保存: {filepath}")
        return str(filepath)
        
    except Exception as e:
        logger.error(f"SQLite保存中にエラーが発生: {e}", exc_info=True)
        raise


def prepare_record(
    extracted_data: Dict[str, str],
    source: str = "auto_batch",
) -> Dict[str, str]:
    """
    抽出データを保存用レコード形式に変換する
    
    Args:
        extracted_data: 抽出されたデータ
        source: ソース識別子
        
    Returns:
        保存用レコード
    """
    from .utils import extract_domain
    
    url = extracted_data.get("website_url", "")
    domain = extract_domain(url)
    
    return {
        "email": extracted_data.get("email", "").strip(),
        "company_name": extracted_data.get("company_name", "").strip(),
        "address": extracted_data.get("address", "").strip(),
        "website_url": url,
        "industry": extracted_data.get("industry", "").strip(),
        "domain": domain,
        "source": source,
        "created_at": datetime.now().isoformat(),
    }


def load_seen() -> Tuple[Set[str], Set[str]]:
    """
    過去に取得したメールアドレスとドメインを読み込む
    履歴ファイルとマスターリストの両方から読み込む
    
    Returns:
        (過去のメールアドレスセット, 過去のドメインセット)
    """
    emails: Set[str] = set()
    domains: Set[str] = set()
    
    # 履歴ファイルから読み込み
    if HISTORY_PATH.exists():
        try:
            with HISTORY_PATH.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = row.get("email", "").strip().lower()
                    domain = row.get("domain", "").strip().lower()
                    
                    if email and "@" in email:
                        emails.add(email)
                    if domain:
                        domains.add(domain)
            
            logger.info(f"履歴ファイルから {len(emails)} 件のメールアドレスと {len(domains)} 件のドメインを読み込みました")
        except Exception as e:
            logger.warning(f"履歴ファイルの読み込み中にエラーが発生: {e}")
    else:
        logger.info("履歴ファイルが存在しないため、スキップします")
    
    # マスターリストからも読み込み
    MASTER_FILE = Path("data/output/master_leads.csv")
    if MASTER_FILE.exists():
        try:
            master_emails_count = 0
            master_domains_count = 0
            with MASTER_FILE.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = row.get("email", "").strip().lower()
                    # マスターリストにはdomainカラムがない場合があるので、emailから抽出
                    if email and "@" in email:
                        if email not in emails:
                            emails.add(email)
                            master_emails_count += 1
                        # ドメインを抽出
                        domain = email.split("@")[-1] if "@" in email else ""
                        if domain and domain not in domains:
                            domains.add(domain)
                            master_domains_count += 1
            
            logger.info(f"マスターリストから {master_emails_count} 件のメールアドレスと {master_domains_count} 件のドメインを追加しました")
        except Exception as e:
            logger.warning(f"マスターリストの読み込み中にエラーが発生: {e}")
    else:
        logger.info("マスターリストが存在しないため、スキップします")
    
    logger.info(f"合計 {len(emails)} 件のメールアドレスと {len(domains)} 件のドメインを読み込みました（履歴ファイル + マスターリスト）")
    
    return emails, domains


def append_to_history(records: List[Dict[str, str]]) -> None:
    """
    取得したレコードを履歴ファイルに追記する
    
    Args:
        records: 追記するレコードのリスト
    """
    if not records:
        return
    
    try:
        # ディレクトリを作成
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # ファイルが存在するかチェック
        is_new = not HISTORY_PATH.exists()
        
        # 履歴ファイルは内部処理用なので、全カラムを保持
        fieldnames = [
            "email",
            "company_name",
            "address",
            "website_url",
            "industry",
            "domain",
            "source",
            "created_at",
        ]
        
        with HISTORY_PATH.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if is_new:
                writer.writeheader()
            
            for record in records:
                writer.writerow(record)
        
        logger.info(f"{len(records)} 件のレコードを履歴ファイルに追記しました")
    except Exception as e:
        logger.error(f"履歴ファイルへの追記中にエラーが発生: {e}", exc_info=True)


def filter_new_records(
    records: List[Dict[str, str]],
    seen_emails: Set[str],
    seen_domains: Set[str],
) -> List[Dict[str, str]]:
    """
    過去に取得したレコードを除外し、新規レコードのみを返す
    ドメイン重複は削除（1ドメイン1メールアドレスのみ保持）
    
    Args:
        records: フィルタリング対象のレコードリスト
        seen_emails: 過去に取得したメールアドレスのセット
        seen_domains: 過去に取得したドメインのセット
        
    Returns:
        新規レコードのみのリスト（ドメイン重複なし）
    """
    new_records: List[Dict[str, str]] = []
    today_emails: Set[str] = set()
    today_domains: Set[str] = set()
    
    for record in records:
        email = record.get("email", "").strip().lower()
        domain = record.get("domain", "").strip().lower()
        
        # メールがない / @がない → そもそも捨てる
        if not email or "@" not in email:
            continue
        
        # ドメインが取得できない場合は、メールアドレスから抽出
        if not domain:
            domain = email.split("@")[-1] if "@" in email else ""
        
        # 過去 or 今日すでに出たメールアドレスならスキップ
        if email in seen_emails or email in today_emails:
            logger.debug(f"重複メールアドレスのため除外: {email}")
            continue
        
        # 過去 or 今日すでに出たドメインならスキップ（ドメイン重複を削除）
        if domain in seen_domains or domain in today_domains:
            logger.debug(f"重複ドメインのため除外: {email} (ドメイン: {domain})")
            continue
        
        # 今日のセットに追加
        today_emails.add(email)
        today_domains.add(domain)
        new_records.append(record)
    
    logger.info(
        f"重複除外: {len(records)} 件 → {len(new_records)} 件（{len(records) - len(new_records)} 件を除外）"
    )
    
    return new_records


def check_already_run_today() -> bool:
    """
    今日既に実行済みかどうかをチェックする
    
    Returns:
        今日既に実行済みの場合True
    """
    if not LOCK_PATH.exists():
        return False
    
    try:
        last_run_date = LOCK_PATH.read_text(encoding="utf-8").strip()
        today = datetime.now().strftime("%Y%m%d")
        return last_run_date == today
    except Exception as e:
        logger.warning(f"実行ロックファイルの読み込み中にエラーが発生: {e}")
        return False


def mark_as_run_today() -> None:
    """
    今日実行済みとしてマークする
    """
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        LOCK_PATH.write_text(today, encoding="utf-8")
        logger.info(f"実行ロックファイルを更新しました: {today}")
    except Exception as e:
        logger.error(f"実行ロックファイルの更新中にエラーが発生: {e}", exc_info=True)

