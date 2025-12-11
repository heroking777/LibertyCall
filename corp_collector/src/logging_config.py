"""ログ設定モジュール"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: str,
    log_level: str = "INFO",
    log_to_console: bool = True,
) -> logging.Logger:
    """
    ログ設定を初期化する
    
    Args:
        log_dir: ログファイルを保存するディレクトリ
        log_level: ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_to_console: コンソールにも出力するか
        
    Returns:
        設定済みのロガー
    """
    # ログディレクトリを作成
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # ログファイル名（日付付き）
    today = datetime.now().strftime("%Y%m%d")
    log_file = Path(log_dir) / f"app_{today}.log"
    
    # ログレベルを文字列から変換
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # ロガーを取得
    logger = logging.getLogger("corp_collector")
    logger.setLevel(level)
    
    # 既存のハンドラをクリア（重複防止）
    logger.handlers.clear()
    
    # フォーマッター
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # ファイルハンドラ
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # コンソールハンドラ
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger

