"""送信前メールアドレス検証モジュール"""
import smtplib
import logging
import dns.resolver
import random
import string

logger = logging.getLogger(__name__)

# キャッシュ（プロセス内で同一ドメインの再検証を避ける）
_mx_cache = {}
_catchall_cache = {}
_verify_cache = {}

def get_mx_host(domain):
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx_host = str(mx_records[0].exchange).rstrip('.')
        _mx_cache[domain] = mx_host
        return mx_host
    except:
        try:
            dns.resolver.resolve(domain, 'A')
            _mx_cache[domain] = domain
            return domain
        except:
            _mx_cache[domain] = None
            return None

def is_catchall(domain, mx_host):
    if domain in _catchall_cache:
        return _catchall_cache[domain]
    random_local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=20))
    test_email = f"{random_local}@{domain}"
    try:
        server = smtplib.SMTP(timeout=5)
        server.connect(mx_host, 25)
        server.helo('libcall.com')
        server.mail('verify@libcall.com')
        code, _ = server.rcpt(test_email)
        server.quit()
        result = code in (250, 251)
        _catchall_cache[domain] = result
        return result
    except:
        _catchall_cache[domain] = False
        return False

def verify_email(email):
    """送信前にメールアドレスの存在を検証
    Returns: (bool, str) = (送信してよいか, 理由)
    """
    email = email.strip().lower()
    if email in _verify_cache:
        return _verify_cache[email]

    domain = email.split('@')[-1]
    
    # MXチェック
    mx_host = get_mx_host(domain)
    if not mx_host:
        result = (False, 'no_mx')
        _verify_cache[email] = result
        logger.info(f"検証FAIL(MXなし): {email}")
        return result
    
    # Catch-allはスキップ（検証不能、送信OK）
    if is_catchall(domain, mx_host):
        result = (True, 'catchall')
        _verify_cache[email] = result
        return result
    
    # SMTP RCPT TO チェック
    try:
        server = smtplib.SMTP(timeout=5)
        server.connect(mx_host, 25)
        server.helo('libcall.com')
        server.mail('verify@libcall.com')
        code, msg = server.rcpt(email)
        server.quit()
        
        if code in (250, 251):
            result = (True, 'smtp_ok')
        elif code in (550, 551, 552, 553):
            result = (False, f'smtp_reject_{code}')
            logger.info(f"検証FAIL(SMTP {code}): {email}")
        elif code in (450, 451, 452):
            # 一時エラーは送信OK（グレーリスティング等）
            result = (True, 'smtp_tempfail')
        else:
            result = (True, f'smtp_unknown_{code}')
        
        _verify_cache[email] = result
        return result
    except smtplib.SMTPServerDisconnected:
        result = (True, 'smtp_disconnected')
        _verify_cache[email] = result
        return result
    except Exception as e:
        # 接続失敗は送信OK（検証不能）
        result = (True, f'smtp_error')
        _verify_cache[email] = result
        return result
