"""
SendGrid Analytics API
バウンス率・スパムレポート率を取得してウォームアップ制御
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
from sendgrid import SendGridAPIClient
from dotenv import load_dotenv
from pathlib import Path

# .envファイルを読み込む
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")


def get_today_stats() -> Tuple[Dict[str, int], float, float]:
    """
    今日のSendGrid統計を取得
    
    Returns:
        (stats_dict, bounce_rate, spam_rate) のタプル
        stats_dict: 各種統計数値
        bounce_rate: バウンス率（%）
        spam_rate: スパムレポート率（%）
    """
    if not SENDGRID_API_KEY:
        raise ValueError("SENDGRID_API_KEYが設定されていません")
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        
        # 今日の日付範囲を取得
        today = datetime.now().date().strftime("%Y-%m-%d")
        start_date = today
        end_date = today  # 1日分のみ
        
        # SendGrid Statistics APIを呼び出し
        query_params = {
            "start_date": start_date,
            "end_date": end_date,
            "aggregated_by": "day"
        }
        
        response = sg.client.stats.get(query_params=query_params)
        
        if response.status_code != 200:
            raise Exception(f"SendGrid APIエラー: {response.status_code}")
        
        data = json.loads(response.body)
        
        if not data or len(data) == 0:
            # データがない場合
            return {
                "delivered": 0,
                "bounces": 0,
                "spam_reports": 0,
                "requests": 0
            }, 0.0, 0.0
        
        # 最新日の統計を取得
        today_stats = data[0]["stats"][0]["metrics"]
        
        delivered = today_stats.get("delivered", 0)
        bounces = today_stats.get("bounces", 0)
        spam_reports = today_stats.get("spam_reports", 0)
        requests = today_stats.get("requests", 0)
        
        stats_dict = {
            "delivered": delivered,
            "bounces": bounces,
            "spam_reports": spam_reports,
            "requests": requests
        }
        
        # バウンス率とスパムレポート率を計算
        if delivered > 0:
            bounce_rate = (bounces / requests) * 100 if requests > 0 else 0.0
            spam_rate = (spam_reports / delivered) * 100 if delivered > 0 else 0.0
        else:
            bounce_rate = 0.0
            spam_rate = 0.0
        
        return stats_dict, bounce_rate, spam_rate
        
    except Exception as e:
        print(f"SendGrid統計取得エラー: {e}")
        # エラー時は例外をそのままraise
        raise


def get_yesterday_stats() -> Tuple[Dict[str, int], float, float]:
    """
    昨日のSendGrid統計を取得
    
    Returns:
        (stats_dict, bounce_rate, spam_rate) のタプル
        stats_dict: 各種統計数値
        bounce_rate: バウンス率（%）
        spam_rate: スパムレポート率（%）
    """
    if not SENDGRID_API_KEY:
        raise ValueError("SENDGRID_API_KEYが設定されていません")
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        
        # 昨日の日付範囲を取得
        yesterday = datetime.now().date() - timedelta(days=1)
        start_date = yesterday.strftime("%Y-%m-%d")
        end_date = start_date  # 1日分のみ
        
        # SendGrid Statistics APIを呼び出し
        query_params = {
            "start_date": start_date,
            "end_date": end_date,
            "aggregated_by": "day"
        }
        
        response = sg.client.stats.get(query_params=query_params)
        
        if response.status_code != 200:
            raise Exception(f"SendGrid APIエラー: {response.status_code}")
        
        data = json.loads(response.body)
        
        if not data or len(data) == 0:
            # データがない場合
            return {
                "delivered": 0,
                "bounces": 0,
                "spam_reports": 0,
                "requests": 0
            }, 0.0, 0.0
        
        # 最新日の統計を取得
        yesterday_stats = data[0]["stats"][0]["metrics"]
        
        delivered = yesterday_stats.get("delivered", 0)
        bounces = yesterday_stats.get("bounces", 0)
        spam_reports = yesterday_stats.get("spam_reports", 0)
        requests = yesterday_stats.get("requests", 0)
        
        stats_dict = {
            "delivered": delivered,
            "bounces": bounces,
            "spam_reports": spam_reports,
            "requests": requests
        }
        
        # バウンス率とスパムレポート率を計算
        if delivered > 0:
            bounce_rate = (bounces / requests) * 100 if requests > 0 else 0.0
            spam_rate = (spam_reports / delivered) * 100 if delivered > 0 else 0.0
        else:
            bounce_rate = 0.0
            spam_rate = 0.0
        
        return stats_dict, bounce_rate, spam_rate
        
    except Exception as e:
        print(f"SendGrid統計取得エラー: {e}")
        # エラー時は例外をそのままraise
        raise


def calculate_daily_limit(current_limit: int, bounce_rate: float, spam_rate: float, 
                         max_limit: int = 5000) -> int:
    """
    翌日の送信上限を計算
    
    Args:
        current_limit: 現在の送信上限
        bounce_rate: バウンス率（%）
        spam_rate: スパムレポート率（%）
        max_limit: 最大送信上限
    
    Returns:
        新しい送信上限
    """
    # バウンス率とスパムレポート率に基づいて制御
    if bounce_rate > 10 or spam_rate > 0.1:
        # バウンス率>10%またはスパム率>0.1% → 半減
        new_limit = max(1, current_limit // 2)
        reason = "バウンス率またはスパムレポートが閾値を超えたため半減"
    elif bounce_rate >= 5 or spam_rate >= 0.05:
        # バウンス率5-10%またはスパム率0.05-0.1% → 据え置き
        new_limit = current_limit
        reason = "バウンス率またはスパムレポートが警告レベルのため据え置き"
    else:
        # バウンス率<5%かつスパム率<0.05% → 1.5倍
        new_limit = min(max_limit, int(current_limit * 1.5))
        reason = "バウンス率・スパムレポートが良好なため増加"
    
    print(f"送信上限制御: {current_limit} → {new_limit} ({reason})")
    print(f"バウンス率: {bounce_rate:.2f}%, スパム率: {spam_rate:.2f}%")
    
    return new_limit


def save_daily_limit(limit: int, date: str = None) -> None:
    """
    当日の送信上限を保存
    
    Args:
        limit: 送信上限
        date: 日付（YYYY-MM-DD形式、デフォルトは今日）
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    limit_data = {
        "date": date,
        "daily_limit": limit,
        "updated_at": datetime.now().isoformat()
    }
    
    # 保存先ファイルパス
    project_root = Path(__file__).parent.parent
    limit_file = project_root / "email_sender" / "daily_limit.json"
    
    try:
        with open(limit_file, "w", encoding="utf-8") as f:
            json.dump(limit_data, f, indent=2, ensure_ascii=False)
        
        print(f"送信上限を保存: {limit}件（{date}）")
        
    except Exception as e:
        print(f"送信上限保存エラー: {e}")


def load_daily_limit(date: str = None) -> Optional[int]:
    """
    指定日の送信上限を読み込み
    
    Args:
        date: 日付（YYYY-MM-DD形式、デフォルトは今日）
    
    Returns:
        送信上限、ファイルが存在しない場合はNone
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    project_root = Path(__file__).parent.parent
    limit_file = project_root / "email_sender" / "daily_limit.json"
    
    try:
        if not limit_file.exists():
            return None
        
        with open(limit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if data.get("date") == date:
            return data.get("daily_limit")
        else:
            return None
            
    except Exception as e:
        print(f"送信上限読み込みエラー: {e}")
        return None


def _load_current_limit_raw():
    """daily_limit.jsonからdaily_limitの値を日付チェックなしで読む"""
    try:
        limit_file = Path(__file__).parent / "daily_limit.json"
        with open(limit_file, 'r') as f:
            data = json.load(f)
        return data.get("daily_limit")
    except Exception:
        return None


def update_daily_limit_automatically():
    """SendGrid統計に基づいて翌日の送信上限を自動更新"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 現在のlimitを日付チェックなしで読む
    current_limit = _load_current_limit_raw()
    if current_limit is None:
        current_limit = 50
    
    try:
        # 昨日の統計を取得
        stats, bounce_rate, spam_rate = get_yesterday_stats()
        new_limit = calculate_daily_limit(current_limit, bounce_rate, spam_rate)
    except Exception as e:
        print(f"SendGrid統計取得エラー: {e}")
        print(f"上限据え置き: {current_limit}")
        new_limit = current_limit
    
    save_daily_limit(new_limit, tomorrow)
    print(f"翌日の送信上限を更新: {current_limit} → {new_limit} ({tomorrow})")
    return new_limit


if __name__ == "__main__":
    # テスト実行
    limit = update_daily_limit_automatically()
    print(f"今日の送信上限: {limit}件")
