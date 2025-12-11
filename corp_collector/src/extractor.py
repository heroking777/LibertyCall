"""OpenAI APIを使用した情報抽出モジュール"""

import json
import logging
import time
from typing import Dict, Optional

from openai import OpenAI

logger = logging.getLogger("corp_collector.extractor")

# システムプロンプト
SYSTEM_PROMPT = """あなたは日本国内の法人の公式サイトを解析する専門家です。
以下のルールに従って、HTMLから法人情報を抽出してください。

【重要なルール】
1. 日本国内の「法人」の公式サイトを前提に解析すること
2. 医療系・士業系など個人事業主が多い業種では、法人格（医療法人、税理士法人、株式会社など）がない場合は「個人」とみなして除外すること
3. フリーメール（gmail.com / yahoo.co.jp / outlook.com 等）は除外すること
4. 患者専用・予約専用・採用専用のメールアドレスは除外すること
5. 見つからない項目は空文字 "" とする
6. 出力は必ず以下のJSON形式のみとする（他の説明文は不要）：

{
  "company_name": "...",
  "email": "...",
  "address": "...",
  "website_url": "...",
  "industry": "..."
}

【個人事業主の除外ルール（最重要）】
個人クリニック、個人事業主、個人開業の士業事務所、個人の工務店などと判断した場合は、
必ず以下の空データを返してください：

{
  "company_name": "",
  "email": "",
  "address": "",
  "website_url": "...",
  "industry": ""
}

法人格（医療法人、株式会社、有限会社、合同会社、税理士法人、社労士法人、司法書士法人、社会福祉法人など）が
明示的に記載されていない場合は、個人事業主と判断して空データを返してください。

【業種カテゴリ】
- 医療法人
- 美容医療
- 不動産
- 工務店・リフォーム
- 介護施設
- 士業法人
- （該当しない場合は空文字 ""）

【メールアドレスの優先順位】
1. info@ / contact@ / support@ / sales@ などの代表的な問い合わせ用メール
2. その他の法人の代表メールアドレス
3. 個人事業主やフリーメールは除外"""


def extract_corp_info(
    html: str,
    url: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    industry_hint: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> Optional[Dict[str, str]]:
    """
    OpenAI APIを使用してHTMLから法人情報を抽出する
    
    Args:
        html: 解析対象のHTML文字列
        url: 元のURL
        api_key: OpenAI APIキー
        model: 使用するモデル名
        industry_hint: 業種のヒント（オプション）
        max_retries: 最大リトライ回数
        retry_delay: リトライ時の待機時間（秒）
        
    Returns:
        抽出した情報の辞書。失敗時はNone
    """
    client = OpenAI(api_key=api_key)
    
    # ユーザープロンプトを構築
    user_prompt = f"""以下のHTMLから法人情報を抽出してください。

URL: {url}
"""
    if industry_hint:
        user_prompt += f"\n業種のヒント: {industry_hint}\n"
    
    user_prompt += f"\nHTML:\n{html[:30000]}"  # HTMLが長すぎる場合は切り詰め
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            
            content = response.choices[0].message.content
            if not content:
                logger.warning(f"URL '{url}' の抽出結果が空でした")
                return None
            
            # JSONをパース
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(
                    f"URL '{url}' の抽出結果のJSON解析に失敗: {e}\n内容: {content}"
                )
                return None
            
            # 必須フィールドをチェック
            required_fields = ["company_name", "email", "address", "website_url", "industry"]
            for field in required_fields:
                if field not in result:
                    result[field] = ""
            
            # website_urlを設定
            result["website_url"] = url
            
            # バリデーション: 会社名の法人チェック
            company_name = result.get("company_name", "").strip()
            if not company_name:
                logger.debug(f"URL '{url}': 会社名が見つかりませんでした")
                return None
            
            # 法人フィルタチェック
            from .utils import is_valid_corporation
            if not is_valid_corporation(company_name):
                logger.debug(
                    f"URL '{url}': 法人として無効なため除外: {company_name}"
                )
                return None
            
            # バリデーション: メールアドレスが空またはフリーメールの場合は除外
            email = result.get("email", "").strip()
            if not email:
                logger.debug(f"URL '{url}': メールアドレスが見つかりませんでした")
                return None
            
            # フリーメールチェック（extractor内でも簡易チェック）
            free_mail_domains = ["gmail.com", "yahoo.co.jp", "yahoo.com", "outlook.com", "hotmail.com"]
            email_lower = email.lower()
            if any(f"@{domain}" in email_lower for domain in free_mail_domains):
                logger.debug(f"URL '{url}': フリーメールアドレスのため除外: {email}")
                return None
            
            logger.info(
                f"URL '{url}' から情報を抽出: {company_name} / {email}"
            )
            return result
            
        except Exception as e:
            error_msg = str(e)
            
            # レートリミットエラーの場合
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                wait_time = retry_delay * (attempt + 1)
                logger.warning(
                    f"URL '{url}' の抽出中にレートリミットエラーが発生。"
                    f"{wait_time}秒待機してリトライします（試行 {attempt + 1}/{max_retries}）"
                )
                time.sleep(wait_time)
                continue
            
            logger.error(
                f"URL '{url}' の抽出中にエラーが発生: {e}（試行 {attempt + 1}/{max_retries}）",
                exc_info=True,
            )
            
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    logger.error(f"URL '{url}' の情報抽出に失敗しました（最大リトライ回数に達しました）")
    return None

