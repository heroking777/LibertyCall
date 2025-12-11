"""Google Custom Search Engine (CSE) クライアント"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("corp_collector.cse_client")

# クエリ状態ファイルのパス
STATE_PATH = Path("data/state/query_state.json")


def load_query_state() -> Dict:
    """
    クエリごとの状態（次のstart値）を読み込む
    
    Returns:
        クエリ状態の辞書
    """
    if not STATE_PATH.exists():
        return {"queries": {}}
    
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"状態ファイルの読み込み中にエラーが発生: {e}")
        return {"queries": {}}


def save_query_state(state: Dict) -> None:
    """
    クエリごとの状態を保存する
    
    Args:
        state: クエリ状態の辞書
    """
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"状態ファイルの保存中にエラーが発生: {e}", exc_info=True)


def fetch_urls(
    queries: List[str],
    api_key: str,
    search_engine_id: str,
    max_queries: int = 100,
    results_per_query: int = 10,
    timeout: float = 30.0,
) -> List[str]:
    """
    Google CSE APIを使用してURLリストを取得する
    
    Args:
        queries: 検索クエリのリスト
        api_key: Google CSE APIキー
        search_engine_id: 検索エンジンID
        max_queries: 最大クエリ数（デフォルト100）
        results_per_query: クエリあたりの結果数（デフォルト10）
        timeout: リクエストタイムアウト（秒）
        
    Returns:
        取得したURLのリスト（重複除外済み）
    """
    all_urls: List[str] = []
    executed_queries = 0
    
    base_url = "https://www.googleapis.com/customsearch/v1"
    
    # クエリ状態を読み込む
    state = load_query_state()
    
    for query in queries:
        if executed_queries >= max_queries:
            logger.warning(
                f"最大クエリ数({max_queries})に達したため、残りのクエリをスキップします"
            )
            break
        
        # クエリごとの状態を取得（デフォルトはstart=1）
        q_state = state["queries"].get(query, {"start": 1})
        start = q_state.get("start", 1)
        
        # startが91を超えたらリセット（CSEは最大91まで）
        if start > 91:
            logger.info(f"クエリ '{query}' は全ページを取得済みのため、リセットします")
            start = 1
            q_state["start"] = 1
        
        logger.info(f"クエリ実行中: {query} (start={start})")
        
        # ページングループ（最大10ページ分取得、またはresults_per_query件取得まで）
        query_urls: List[str] = []
        current_start = start
        max_pages = 10  # 1クエリあたり最大10ページ
        
        for page in range(max_pages):
            # 必要な件数が集まったら終了
            if len(query_urls) >= results_per_query:
                break
            
            # リトライループ
            max_retries = 3
            retry_delay = 2.0
            success = False
            
            for attempt in range(max_retries):
                try:
                    params = {
                        "key": api_key,
                        "cx": search_engine_id,
                        "q": query,
                        "num": results_per_query,
                        "start": current_start,
                    }
                    
                    if attempt > 0:
                        logger.info(f"クエリ再試行中 ({attempt + 1}/{max_retries}): {query} (start={current_start})")
                    
                    with httpx.Client(timeout=timeout) as client:
                        response = client.get(base_url, params=params)
                        
                        # ステータスコードチェック
                        if response.status_code == 200:
                            data = response.json()
                            
                            # 結果からURLを抽出
                            page_urls = []
                            if "items" in data:
                                for item in data["items"]:
                                    if "link" in item:
                                        page_urls.append(item["link"])
                            
                            query_urls.extend(page_urls)
                            
                            # 次のページがあるかチェック
                            if len(page_urls) < results_per_query:
                                # これ以上結果がない
                                break
                            
                            success = True
                            break
                    
                        # エラーレスポンスの処理
                        error_body = response.text
                        status_code = response.status_code
                        
                        # リトライ可能なエラー（429, 400, 500系）
                        if status_code in [429, 400, 500, 502, 503, 504]:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (attempt + 1)
                                logger.warning(
                                    "クエリ '%s' の実行中にHTTPエラーが発生: %s, body=%s. "
                                    "%s秒待機してリトライします（試行 %s/%s）",
                                    query,
                                    status_code,
                                    error_body[:500],  # エラーメッセージを500文字に制限
                                    wait_time,
                                    attempt + 1,
                                    max_retries,
                                )
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error(
                                    "クエリ '%s' の実行中にHTTPエラーが発生: %s, body=%s. "
                                    "最大リトライ回数に達しました",
                                    query,
                                    status_code,
                                    error_body[:500],
                                )
                                break
                        else:
                            # リトライ不可なエラー（401, 403など）
                            logger.error(
                                "クエリ '%s' の実行中にHTTPエラーが発生: %s, body=%s",
                                query,
                                status_code,
                                error_body[:500],
                            )
                            break
                    
                except httpx.HTTPStatusError as e:
                    error_body = e.response.text if hasattr(e.response, 'text') else str(e)
                    status_code = e.response.status_code if hasattr(e.response, 'status_code') else 0
                    
                    # リトライ可能なエラー
                    if status_code in [429, 400, 500, 502, 503, 504]:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (attempt + 1)
                            logger.warning(
                                "クエリ '%s' の実行中にHTTPエラーが発生: %s, body=%s. "
                                "%s秒待機してリトライします（試行 %s/%s）",
                                query,
                                status_code,
                                error_body[:500],
                                wait_time,
                                attempt + 1,
                                max_retries,
                            )
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(
                                "クエリ '%s' の実行中にHTTPエラーが発生: %s, body=%s. "
                                "最大リトライ回数に達しました",
                                query,
                                status_code,
                                error_body[:500],
                            )
                            break
                    else:
                        logger.error(
                            "クエリ '%s' の実行中にHTTPエラーが発生: %s, body=%s",
                            query,
                            status_code,
                            error_body[:500],
                        )
                        break
                        
                except httpx.TimeoutException:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (attempt + 1)
                        logger.warning(
                            "クエリ '%s' の実行がタイムアウトしました。"
                            "%s秒待機してリトライします（試行 %s/%s）",
                            query,
                            wait_time,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(
                            f"クエリ '{query}' の実行がタイムアウトしました（最大リトライ回数に達しました）"
                        )
                        break
                except Exception as e:
                    logger.error(
                        f"クエリ '{query}' の実行中にエラーが発生: {e}",
                        exc_info=True,
                    )
                    break
            
            if not success:
                # リトライに失敗した場合はこのページをスキップ
                break
            
            # 次のページへ
            current_start += results_per_query
            
            # レートリミット対策（ページ間に少し待機）
            time.sleep(0.5)
        
        # クエリごとのURLを追加
        if query_urls:
            all_urls.extend(query_urls)
            executed_queries += 1
            logger.info(f"クエリ '{query}' から合計 {len(query_urls)} 件のURLを取得")
        
        # 次のstart値を保存
        q_state["start"] = current_start
        state["queries"][query] = q_state
        
        # 成功した場合のみ待機
        if query_urls:
            # レートリミット対策（クエリ間に少し待機）
            time.sleep(0.5)
    
    # 状態を保存
    save_query_state(state)
    
    # 重複除外
    unique_urls = list(dict.fromkeys(all_urls))  # 順序を保持しつつ重複除外
    
    logger.info(
        f"合計 {executed_queries} クエリを実行し、{len(unique_urls)} 件のユニークなURLを取得しました"
    )
    
    return unique_urls, executed_queries

