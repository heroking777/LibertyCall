"""メインエントリーポイント"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

import tomli

from .cse_client import fetch_urls
from .extractor import extract_corp_info
from .fetcher import fetch_html
from .logging_config import setup_logging
from .storage import (
    append_to_history,
    check_already_run_today,
    filter_new_records,
    load_seen,
    mark_as_run_today,
    prepare_record,
    save_records_to_csv,
    save_records_to_sqlite,
)
from .utils import is_excluded_email, is_free_mail

logger = logging.getLogger("corp_collector.main")


def _send_collection_notification(
    executed_queries: int,
    extracted_count: int,
    duplicate_count: int,
    new_records_count: int,
) -> None:
    """
    メールアドレス収集完了の通知メールを送信
    
    Args:
        executed_queries: 実行したクエリ数
        extracted_count: 抽出成功数
        duplicate_count: 重複件数
        new_records_count: 新規追加件数
    """
    try:
        import sys
        from pathlib import Path
        
        # email_senderモジュールをインポート
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))
        
        from email_sender.sendgrid_client import send_notification_email
        from datetime import datetime
        
        # 通知メールの本文を作成
        body_lines = [
            "LibertyCall メールアドレス収集システム",
            "",
            f"完了日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
            "",
            "=== 収集結果 ===",
            f"使用クエリ数: {executed_queries}件",
            f"取得件数: {extracted_count}件",
            f"重複: {duplicate_count}件",
            f"結果: {new_records_count}件増えた",
            "",
            "---",
            "LibertyCall メールアドレス収集システム"
        ]
        
        body_text = "\n".join(body_lines)
        
        # 件名
        subject = f"【LibertyCall】メールアドレス収集完了 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        # 通知メールを送信（send_notification_emailのシグネチャに合わせて調整）
        # ただし、この関数は送信件数用なので、直接メール送信を行う
        import os
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, TrackingSettings, ClickTracking
        from dotenv import load_dotenv
        from pathlib import Path
        
        # .envファイルを読み込む（絶対パスで指定、Webルート外）
        env_path = Path(__file__).parent.parent.parent / ".env"
        load_dotenv(dotenv_path=env_path)
        
        SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
        SENDER_EMAIL = os.getenv("SENDER_EMAIL", "sales@libcall.com")
        NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")
        
        if not NOTIFICATION_EMAIL:
            logger.warning("通知先メールアドレスが設定されていません（NOTIFICATION_EMAIL）")
            return
        
        if not SENDGRID_API_KEY:
            logger.warning("SENDGRID_API_KEYが設定されていません")
            return
        
        from_email = f"LibertyCall サポート <{SENDER_EMAIL}>"
        
        message = Mail(
            from_email=from_email,
            to_emails=NOTIFICATION_EMAIL,
            subject=subject,
            plain_text_content=body_text
        )
        
        # クリックトラッキングを無効化
        tracking_settings = TrackingSettings()
        click_tracking = ClickTracking(enable=False)
        tracking_settings.click_tracking = click_tracking
        message.tracking_settings = tracking_settings
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"収集完了通知メールを送信しました: {NOTIFICATION_EMAIL} | ステータス: {response.status_code}")
        
    except Exception as e:
        logger.error(f"通知メール送信エラー: {e}", exc_info=True)


def load_config(config_path: str) -> dict:
    """
    設定ファイルを読み込む
    
    Args:
        config_path: 設定ファイルのパス
        
    Returns:
        設定辞書
    """
    config_file = Path(config_path)
    if not config_file.exists():
        logger.error(f"設定ファイルが見つかりません: {config_path}")
        sys.exit(1)
    
    try:
        with open(config_file, "rb") as f:
            config = tomli.load(f)
        logger.info(f"設定ファイルを読み込みました: {config_path}")
        return config
    except Exception as e:
        logger.error(f"設定ファイルの読み込みに失敗: {e}", exc_info=True)
        sys.exit(1)


def load_queries(queries_path: str) -> List[str]:
    """
    クエリファイルを読み込む
    
    Args:
        queries_path: クエリファイルのパス
        
    Returns:
        クエリのリスト
    """
    queries_file = Path(queries_path)
    
    # ファイルが存在しない場合はexampleファイルをチェック
    if not queries_file.exists():
        example_file = Path(queries_path.replace(".txt", ".example.txt"))
        if example_file.exists():
            logger.warning(
                f"クエリファイル '{queries_path}' が見つかりません。"
                f"例ファイル '{example_file}' を使用します。"
            )
            queries_file = example_file
        else:
            logger.error(f"クエリファイルが見つかりません: {queries_path}")
            sys.exit(1)
    
    try:
        with open(queries_file, "r", encoding="utf-8") as f:
            queries = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        logger.info(f"{len(queries)} 件のクエリを読み込みました: {queries_file}")
        return queries
    except Exception as e:
        logger.error(f"クエリファイルの読み込みに失敗: {e}", exc_info=True)
        sys.exit(1)


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description="法人向けメールアドレス収集バッチ")
    parser.add_argument(
        "--config",
        default="config/settings.toml",
        help="設定ファイルのパス（デフォルト: config/settings.toml）",
    )
    parser.add_argument(
        "--queries",
        default="config/queries.txt",
        help="クエリファイルのパス（デフォルト: config/queries.txt）",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        help="処理する最大URL数（テスト用）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には保存せずに処理を実行（テスト用）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="1日1回の制限を無視して強制実行（テスト用）",
    )
    
    args = parser.parse_args()
    
    # プロジェクトルートに移動
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # .envファイルを読み込む（/opt/libertycall/.env）
    from dotenv import load_dotenv
    env_path = Path("/opt/libertycall/.env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logger.info(f"環境変数を読み込みました: {env_path}")
    
    # 設定を読み込み
    config = load_config(args.config)
    
    # ログ設定
    log_config = config.get("log", {})
    logger_instance = setup_logging(
        log_dir=log_config.get("directory", "data/logs"),
        log_level=log_config.get("level", "INFO"),
    )
    
    logger.info("=" * 60)
    logger.info("法人向けメールアドレス収集バッチを開始します")
    logger.info("=" * 60)
    
    # 1日1回の制限チェック（--force オプションがない場合）
    if not args.force and not args.dry_run:
        if check_already_run_today():
            logger.warning(
                "今日は既に実行済みです。1日1回の制限により処理を終了します。"
                "強制実行する場合は --force オプションを使用してください。"
            )
            sys.exit(0)
    
    # 過去に取得したメールアドレスとドメインを読み込む
    logger.info("履歴ファイルを読み込み中...")
    seen_emails, seen_domains = load_seen()
    logger.info(f"過去の履歴: {len(seen_emails)} 件のメールアドレス、{len(seen_domains)} 件のドメイン")
    
    # クエリを読み込み
    queries = load_queries(args.queries)
    
    # Google CSE設定
    cse_config = config.get("google_cse", {})
    # 環境変数から優先的に読み込む（セキュリティのため）
    api_key = os.getenv("GOOGLE_CSE_API_KEY") or cse_config.get("api_key")
    search_engine_id = cse_config.get("search_engine_id")
    daily_query_limit = cse_config.get("daily_query_limit", 100)
    
    if not api_key or not search_engine_id:
        logger.error("Google CSE APIキーまたは検索エンジンIDが設定されていません")
        logger.error("環境変数 GOOGLE_CSE_API_KEY を設定するか、settings.toml に api_key を設定してください")
        sys.exit(1)
    
    # URLリストを取得
    logger.info("Google CSEからURLリストを取得中...")
    urls, executed_queries = fetch_urls(
        queries=queries,
        api_key=api_key,
        search_engine_id=search_engine_id,
        max_queries=daily_query_limit,
    )
    
    if not urls:
        logger.warning("取得したURLがありません。処理を終了します。")
        # 通知メールを送信（URLが取得できなかった場合）
        if not args.dry_run:
            _send_collection_notification(
                executed_queries=executed_queries,
                extracted_count=0,
                duplicate_count=0,
                new_records_count=0,
            )
        return
    
    # 最大URL数の制限
    if args.max_urls and len(urls) > args.max_urls:
        logger.info(f"最大URL数制限により、{args.max_urls}件に制限します")
        urls = urls[: args.max_urls]
    
    logger.info(f"処理対象URL数: {len(urls)}")
    
    # クローラー設定
    crawler_config = config.get("crawler", {})
    user_agent = crawler_config.get(
        "user_agent",
        "Mozilla/5.0 (compatible; CorpLeadCollector/1.0)",
    )
    timeout = crawler_config.get("request_timeout_seconds", 20)
    max_retries = crawler_config.get("max_retries", 3)
    sleep_between = crawler_config.get("sleep_between_requests_seconds", 2)
    
    # OpenAI設定
    openai_config = config.get("openai", {})
    # 環境変数から優先的に読み込む（セキュリティのため）
    openai_api_key = os.getenv("OPENAI_API_KEY") or openai_config.get("api_key")
    model = openai_config.get("model", "gpt-4o-mini")
    
    if not openai_api_key:
        logger.error("OpenAI APIキーが設定されていません")
        logger.error("環境変数 OPENAI_API_KEY を設定するか、settings.toml に api_key を設定してください")
        sys.exit(1)
    
    # 統計情報
    total_urls = len(urls)
    html_success_count = 0
    extraction_success_count = 0
    valid_records = []
    
    # URLごとに処理
    logger.info("URLの処理を開始します...")
    for idx, url in enumerate(urls, 1):
        logger.info(f"[{idx}/{total_urls}] 処理中: {url}")
        
        # HTML取得
        html = fetch_html(
            url=url,
            user_agent=user_agent,
            timeout=timeout,
            max_retries=max_retries,
            sleep_between_requests=sleep_between,
        )
        
        if not html:
            logger.warning(f"HTMLの取得に失敗: {url}")
            continue
        
        html_success_count += 1
        
        # 情報抽出
        # 将来的にクエリごとに業種ヒントを付けられるようにする設計
        extracted = extract_corp_info(
            html=html,
            url=url,
            api_key=openai_api_key,
            model=model,
            industry_hint=None,
        )
        
        if not extracted:
            logger.debug(f"情報の抽出に失敗: {url}")
            continue
        
        email = extracted.get("email", "").strip()
        
        # バリデーション
        if not email:
            logger.debug(f"メールアドレスが空: {url}")
            continue
        
        if is_free_mail(email):
            logger.debug(f"フリーメールアドレスのため除外: {email}")
            continue
        
        if is_excluded_email(email):
            logger.debug(f"除外対象のメールアドレス: {email}")
            continue
        
        extraction_success_count += 1
        
        # レコードを準備
        record = prepare_record(extracted, source="auto_batch")
        valid_records.append(record)
        
        logger.info(
            f"抽出成功: {record.get('company_name', 'N/A')} / {email} / {record.get('industry', 'N/A')}"
        )
    
    # サマリログ
    logger.info("=" * 60)
    logger.info("処理サマリ")
    logger.info("=" * 60)
    logger.info(f"総URL数: {total_urls}")
    logger.info(f"HTML取得成功数: {html_success_count}")
    logger.info(f"抽出成功数: {extraction_success_count}")
    logger.info(f"有効レコード数: {len(valid_records)}")
    
    # 重複除外フィルタリング
    duplicate_count = 0
    new_records_count = 0
    if valid_records:
        logger.info("重複除外フィルタリングを実行中...")
        records_before_filter = len(valid_records)
        valid_records = filter_new_records(valid_records, seen_emails, seen_domains)
        new_records_count = len(valid_records)
        duplicate_count = records_before_filter - new_records_count
        logger.info(f"重複除外後: {new_records_count} 件の新規レコード（重複: {duplicate_count}件）")
    
    # 保存処理
    if not args.dry_run and valid_records:
        output_config = config.get("output", {})
        output_dir = output_config.get("directory", "data/output")
        filename_prefix = output_config.get("filename_prefix", "leads")
        output_format = output_config.get("format", "csv")
        
        try:
            if output_format == "sqlite":
                save_records_to_sqlite(
                    records=valid_records,
                    output_dir=output_dir,
                    filename_prefix=filename_prefix,
                )
            else:
                save_records_to_csv(
                    records=valid_records,
                    output_dir=output_dir,
                    filename_prefix=filename_prefix,
                )
            logger.info(f"{len(valid_records)} 件のレコードを保存しました")
            
            # 履歴ファイルに追記
            append_to_history(valid_records)
            
            # 実行済みマーク（DRY-RUNモードでない場合のみ）
            if not args.dry_run:
                mark_as_run_today()
        except Exception as e:
            logger.error(f"保存処理中にエラーが発生: {e}", exc_info=True)
            sys.exit(1)
    elif args.dry_run:
        logger.info("DRY-RUNモードのため、保存は行いませんでした")
    
    # 通知メールを送信（DRY-RUNモードでない場合のみ）
    if not args.dry_run:
        _send_collection_notification(
            executed_queries=executed_queries,
            extracted_count=extraction_success_count,
            duplicate_count=duplicate_count,
            new_records_count=new_records_count,
        )
    
    logger.info("処理が完了しました")


if __name__ == "__main__":
    main()

