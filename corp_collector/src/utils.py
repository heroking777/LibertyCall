"""共通ユーティリティ関数"""

from typing import Optional
from urllib.parse import urlparse


def extract_domain(url: str) -> str:
    """
    URLからドメインを抽出する
    
    Args:
        url: 抽出元のURL
        
    Returns:
        抽出されたドメイン（例: example.co.jp）
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        # www. を除去
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def is_free_mail(email: str) -> bool:
    """
    フリーメールアドレスかどうかを判定する
    
    Args:
        email: チェック対象のメールアドレス
        
    Returns:
        フリーメールの場合True
    """
    if not email:
        return False
    
    email_lower = email.lower()
    free_mail_domains = [
        "gmail.com",
        "yahoo.co.jp",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "live.com",
        "msn.com",
        "aol.com",
        "mail.com",
        "zoho.com",
        "protonmail.com",
        "proton.me",
    ]
    
    for domain in free_mail_domains:
        if f"@{domain}" in email_lower:
            return True
    
    return False


def is_excluded_email(email: str) -> bool:
    """
    除外すべきメールアドレスかどうかを判定する
    （患者専用・予約専用・採用専用など）
    
    Args:
        email: チェック対象のメールアドレス
        
    Returns:
        除外すべき場合True
    """
    if not email:
        return True
    
    email_lower = email.lower()
    excluded_keywords = [
        "patient",
        "reservation",
        "booking",
        "appointment",
        "recruit",
        "career",
        "job",
        "採用",
        "予約",
        "患者",
        "patient@",
        "reservation@",
        "booking@",
        "appointment@",
        "recruit@",
        "career@",
        "job@",
    ]
    
    for keyword in excluded_keywords:
        if keyword in email_lower:
            return True
    
    return False


def is_valid_corporation(company_name: str) -> bool:
    """
    法人として有効かどうかを判定する
    
    以下の条件を満たす必要がある:
    - 除外キーワード（クリニック、医院、歯科など）が含まれていない
    - 必須キーワード（株式会社、医療法人など）が含まれている
    
    Args:
        company_name: チェック対象の会社名
        
    Returns:
        有効な法人の場合True
    """
    if not company_name or not company_name.strip():
        return False
    
    company_name = company_name.strip()
    
    # 除外キーワード（クリニック、医院、歯科などは完全除外）
    exclude_keywords = [
        "クリニック",
        "医院",
        "歯科",
        "動物病院",
        "こども園",
        "幼稚園",
        "保育園",
        "薬局",
        "整骨院",
        "整体院",
        "接骨院",
        "美容室",
        "サロン",
        "理学療法",
        "セラピー",
        "病院",
        "医員",
    ]
    
    # 除外キーワードが含まれている場合は無効
    if any(keyword in company_name for keyword in exclude_keywords):
        return False
    
    # 必須キーワード（法人格が必須）
    must_include = [
        "株式会社",
        "有限会社",
        "合同会社",
        "医療法人",
        "社会福祉法人",
        "一般社団法人",
        "一般財団法人",
        "NPO法人",
        "税理士法人",
        "社労士法人",
        "社会保険労務士法人",
        "司法書士法人",
        "行政書士法人",
        "特定非営利活動法人",
    ]
    
    # 必須キーワードが含まれていない場合は無効
    if not any(keyword in company_name for keyword in must_include):
        return False
    
    return True

