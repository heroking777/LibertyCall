#!/usr/bin/env python3
"""
Twitter/X Automation Scraper Demo
デモ用スクリプト - ダミーデータを生成してCSVに保存
実際のTwitterアクセスは不要です
"""

import json
import csv
import random
from datetime import datetime, timedelta
from typing import List, Dict
from playwright.async_api import async_playwright, Browser, Page


# 設定
TARGET_PROFILES = [
    "AmazonJP",
    "MinaShirakawa",
    "TS_takasho",
    "MatuMoto_Ich1ka",
    "YKm0529",
    "yua_mikami",
    "mayukiito",
    "CO8vK2QNubnvLEy",
    "_ce1010",
    "ruzepiyo",
    "buttifone_DQX",
    "amazonmusicjp",
]
COOKIES_FILE = "cookies.json"
OUTPUT_FILE = "demo_output.csv"
DAYS_THRESHOLD = 7  # 過去7日以内のインタラクション


def load_cookies() -> List[Dict]:
    """
    cookies.jsonからクッキーを読み込む（デモ用）
    
    Returns:
        List[Dict]: クッキーリスト（デモでは空でも可）
    """
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content or content == "[]":
                return []
            cookies_data = json.loads(content)
        
        if isinstance(cookies_data, list):
            return cookies_data if cookies_data else []
        elif isinstance(cookies_data, dict) and "cookies" in cookies_data:
            return cookies_data["cookies"] if cookies_data["cookies"] else []
        else:
            return []
    
    except FileNotFoundError:
        print(f"警告: {COOKIES_FILE} が見つかりません。デモモードで続行します。")
        return []
    except json.JSONDecodeError as e:
        print(f"警告: {COOKIES_FILE} のJSON解析に失敗しました: {e}")
        return []


async def get_latest_tweet_url(page: Page, profile: str) -> str:
    """
    プロフィールページから最新ツイートのURLを取得（デモ用）
    実際にはアクセスせず、ダミーURLを返します
    
    Args:
        page: PlaywrightのPageオブジェクト
        profile: Twitterプロフィール名
    
    Returns:
        str: ダミーのツイートURL
    """
    # デモ用: 実際のアクセスは行わず、ダミーURLを返す
    dummy_tweet_id = random.randint(1000000000000000000, 9999999999999999999)
    return f"https://twitter.com/{profile}/status/{dummy_tweet_id}"


async def extract_comments(page: Page, tweet_url: str, profile: str) -> List[Dict[str, str]]:
    """
    ツイートページからコメントを抽出（デモ用）
    実際には抽出せず、ダミーデータを生成します
    
    Args:
        page: PlaywrightのPageオブジェクト
        tweet_url: ツイートのURL
        profile: プロフィール名
    
    Returns:
        List[Dict[str, str]]: ダミーコメント情報のリスト
    """
    # デモ用: ダミーユーザー名を生成
    dummy_usernames = [
        "user_tanaka", "user_suzuki", "user_yamada",
        "user_watanabe", "user_sato", "user_kobayashi",
        "user_ito", "user_nakamura", "user_kato"
    ]
    
    # ランダムに3-5個のコメントを生成
    num_comments = random.randint(3, 5)
    comments = []
    
    for i in range(num_comments):
        username = random.choice(dummy_usernames)
        # 重複を避ける
        while any(c["username"] == username for c in comments):
            username = random.choice(dummy_usernames)
        
        comments.append({
            "target_profile": profile,
            "username": username,
            "dm_open": random.choice([True, False]),
            "last_interaction": generate_recent_timestamp(),
        })
    
    return comments


def generate_recent_timestamp() -> str:
    """
    過去7日以内のランダムなタイムスタンプを生成（ISO形式）
    
    Returns:
        str: ISO形式のタイムスタンプ
    """
    now = datetime.now()
    days_ago = random.randint(0, DAYS_THRESHOLD)
    hours_ago = random.randint(0, 23)
    minutes_ago = random.randint(0, 59)
    
    timestamp = now - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
    return timestamp.isoformat() + "Z"


def filter_recent_comments(comments: List[Dict[str, str]], days: int = DAYS_THRESHOLD) -> List[Dict[str, str]]:
    """
    過去N日以内のコメントのみをフィルタリング
    
    Args:
        comments: コメント情報のリスト
        days: フィルタリングする日数（デフォルト: 7日）
    
    Returns:
        List[Dict[str, str]]: フィルタリングされたコメントリスト
    """
    if not comments:
        return []
    
    cutoff_date = datetime.now() - timedelta(days=days)
    filtered = []
    
    for comment in comments:
        timestamp_str = comment.get("last_interaction", "")
        
        if not timestamp_str:
            continue
        
        try:
            # ISO形式のタイムスタンプをパース
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if timestamp.tzinfo:
                timestamp = timestamp.replace(tzinfo=None)
            
            if timestamp >= cutoff_date:
                filtered.append(comment)
        
        except Exception as e:
            # パースエラーの場合はスキップ
            continue
    
    return filtered


def save_to_csv(comments: List[Dict[str, str]], filename: str = OUTPUT_FILE):
    """
    コメントをCSVファイルに保存
    
    Args:
        comments: コメント情報のリスト
        filename: 出力ファイル名
    """
    if not comments:
        print("警告: 保存するコメントがありません")
        return
    
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["target_profile", "username", "dm_open", "last_interaction"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(comments)
        
        print(f"✓ 結果を {filename} に保存しました（{len(comments)} 件）")
    
    except Exception as e:
        print(f"エラー: CSVファイルの保存に失敗しました: {e}")


async def process_profile(page: Page, profile: str) -> List[Dict[str, str]]:
    """
    単一のプロフィールを処理
    
    Args:
        page: PlaywrightのPageオブジェクト
        profile: プロフィール名
    
    Returns:
        List[Dict[str, str]]: 抽出されたコメントリスト
    """
    print(f"  処理中: @{profile}")
    
    # 最新ツイートのURLを取得（デモ用）
    tweet_url = await get_latest_tweet_url(page, profile)
    
    # コメントを抽出（デモ用: ダミーデータを生成）
    comments = await extract_comments(page, tweet_url, profile)
    
    # 過去7日以内のコメントをフィルタリング
    recent_comments = filter_recent_comments(comments, DAYS_THRESHOLD)
    
    return recent_comments


async def main():
    """メイン実行関数"""
    print("=" * 60)
    print("Twitter/X Automation Scraper Demo")
    print("=" * 60)
    print("デモモード: 実際のTwitterアクセスは行いません")
    print("ダミーデータを生成してCSVに保存します\n")
    
    # クッキーを読み込む（デモでは使用しないが、形式を確認）
    cookies = load_cookies()
    if cookies:
        print(f"✓ {len(cookies)} 個のクッキーを読み込みました（デモでは使用しません）")
    else:
        print("✓ クッキーなしでデモモードで実行します")
    
    print(f"\n処理対象プロフィール数: {len(TARGET_PROFILES)}")
    print("-" * 60)
    
    async with async_playwright() as p:
        # ヘッドレスブラウザを起動（デモ用: 実際には使用しない）
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            all_comments = []
            
            # 各プロフィールを処理
            for idx, profile in enumerate(TARGET_PROFILES, 1):
                print(f"[{idx}/{len(TARGET_PROFILES)}] @{profile}")
                
                try:
                    comments = await process_profile(page, profile)
                    all_comments.extend(comments)
                    print(f"  ✓ {len(comments)} 件のコメントを抽出\n")
                
                except Exception as e:
                    print(f"  ✗ エラー: {e}\n")
                    continue
            
            # すべてのコメントをCSVに保存
            if all_comments:
                save_to_csv(all_comments, OUTPUT_FILE)
                print("\n" + "=" * 60)
                print("完了!")
                print(f"合計抽出されたコメント数: {len(all_comments)}")
                print(f"処理したプロフィール数: {len(TARGET_PROFILES)}")
                print(f"出力ファイル: {OUTPUT_FILE}")
            else:
                print("\n警告: 抽出されたコメントがありませんでした")
        
        finally:
            await browser.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
