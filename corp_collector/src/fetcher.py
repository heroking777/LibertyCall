"""HTML取得モジュール"""

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger("corp_collector.fetcher")


def fetch_html(
    url: str,
    user_agent: str,
    timeout: float = 20.0,
    max_retries: int = 3,
    sleep_between_requests: float = 2.0,
    max_length: int = 50000,
) -> Optional[str]:
    """
    URLからHTMLを取得する
    
    Args:
        url: 取得対象のURL
        user_agent: User-Agent文字列
        timeout: リクエストタイムアウト（秒）
        max_retries: 最大リトライ回数
        sleep_between_requests: リクエスト間の待機時間（秒）
        max_length: HTMLの最大文字数（超過時はカット）
        
    Returns:
        取得したHTML文字列。失敗時はNone
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.warning(
                        f"URL '{url}' からステータスコード {response.status_code} を取得"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(sleep_between_requests)
                        continue
                    return None
                
                html = response.text
                
                # 文字数制限
                if len(html) > max_length:
                    logger.warning(
                        f"URL '{url}' のHTMLが長すぎるため、{max_length}文字に切り詰めます"
                        f"（元の長さ: {len(html)}文字）"
                    )
                    html = html[:max_length]
                
                logger.debug(f"URL '{url}' から {len(html)} 文字のHTMLを取得")
                return html
                
        except httpx.TimeoutException:
            logger.warning(
                f"URL '{url}' の取得がタイムアウトしました（試行 {attempt + 1}/{max_retries}）"
            )
            if attempt < max_retries - 1:
                time.sleep(sleep_between_requests)
        except httpx.RequestError as e:
            logger.warning(
                f"URL '{url}' の取得中にリクエストエラーが発生: {e}（試行 {attempt + 1}/{max_retries}）"
            )
            if attempt < max_retries - 1:
                time.sleep(sleep_between_requests)
        except Exception as e:
            logger.error(
                f"URL '{url}' の取得中に予期しないエラーが発生: {e}",
                exc_info=True,
            )
            if attempt < max_retries - 1:
                time.sleep(sleep_between_requests)
    
    logger.error(f"URL '{url}' の取得に失敗しました（最大リトライ回数に達しました）")
    return None

