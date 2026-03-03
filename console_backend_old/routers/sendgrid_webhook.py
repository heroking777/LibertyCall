"""
SendGrid Event Webhook受信
SendGridから送信されるイベント（配信成功・バウンス・開封など）を受信して記録
DSN Failure（Google Groups等）の自動検知・除外機能付き
"""

import csv
import re
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter()
logger = logging.getLogger(__name__)

# 有効なSendGridイベント種別
VALID_EVENTS = {
    "processed", "delivered", "bounce", "dropped", "deferred",
    "spamreport", "unsubscribe", "group_unsubscribe",
    "group_resubscribe", "open", "click",
}

# プロジェクトルート（console_backend/routers/ → console_backend/ → libertycall/）
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_PATH = LOG_DIR / "sendgrid_events.csv"
MASTER_LEADS_PATH = PROJECT_ROOT / "email_sender" / "data" / "master_leads.csv"


def _sanitize(value: str) -> str:
    """CSVセーフな1行文字列に変換"""
    if not value:
        return ""
    return value.replace("\r", " ").replace("\n", " ").strip()[:500]


def _detect_dsn_failure(event_data: dict) -> str | None:
    """
    DSN Failure（Google Groups等で不達）を検知し、元の宛先メールを返す。
    検知できなければ None を返す。

    DSNの特徴:
    - reason に "may not exist, or you may not have permission to post" を含む
    - reason に "visit the Help Center at https://support.google.com/a/" を含む
    """
    reason = event_data.get("reason", "") or ""
    # 複数フィールドから探す（SendGridがどこに入れるか不定）
    full_text = " ".join(str(v) for v in event_data.values() if isinstance(v, str))

    dsn_patterns = [
        "may not exist, or you may not have permission to post",
        "group you tried to contact",
        "support.google.com/a/",
    ]

    is_dsn = any(p in reason or p in full_text for p in dsn_patterns)
    if not is_dsn:
        return None

    # 元の宛先を抽出: event_data["email"] にある場合
    email = event_data.get("email", "")
    if email and "@" in email:
        return email.lower().strip()

    return None


def _flag_email_in_master(email: str, reason: str = "dsn_failure_auto") -> bool:
    """master_leads.csv の該当メールに除外フラグを立てる"""
    if not MASTER_LEADS_PATH.exists():
        return False

    try:
        rows = []
        flagged = False
        with open(MASTER_LEADS_PATH, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row.get("email", "").strip().lower() == email:
                    if not row.get("除外", "").strip():
                        row["除外"] = reason
                        flagged = True
                        logger.info(f"DSN自動除外: {email} ({row.get('company_name', '')})")
                rows.append(row)

        if flagged:
            with open(MASTER_LEADS_PATH, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return flagged
    except Exception as e:
        logger.error(f"除外フラグ付与エラー: {email} - {e}")
        return False


@router.post("/sendgrid/events")
async def handle_sendgrid_events(request: Request):
    """
    SendGrid Event Webhook受信
    受信イベントをCSVに記録する（バウンス・自動返信・開封など）
    DSN Failure検知時は自動的にmaster_leadsに除外フラグを付与する
    """
    try:
        events = await request.json()
    except Exception as e:
        return {"status": "error", "message": f"Invalid JSON: {str(e)}"}

    if not isinstance(events, list):
        events = [events]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = LOG_PATH.exists()
    dsn_count = 0

    try:
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow(["email", "event", "reason", "timestamp"])

            for e in events:
                event_type = _sanitize(e.get("event", ""))
                email = _sanitize(e.get("email", ""))
                reason = _sanitize(e.get("reason", ""))

                # 有効なイベントのみCSVに記録（壊れたDSNデータを除外）
                if event_type in VALID_EVENTS:
                    writer.writerow([
                        email,
                        event_type,
                        reason,
                        datetime.utcnow().isoformat(),
                    ])

                # DSN Failure検知 → 自動除外
                dsn_email = _detect_dsn_failure(e)
                if dsn_email:
                    dsn_count += 1
                    _flag_email_in_master(dsn_email, "dsn_failure_auto")
                    # DSNイベント自体もbounceとして記録
                    writer.writerow([
                        dsn_email,
                        "bounce",
                        "DSN Failure (Google Groups or similar)",
                        datetime.utcnow().isoformat(),
                    ])

        return {"status": "ok", "count": len(events), "dsn_detected": dsn_count}

    except Exception as e:
        return {"status": "error", "message": f"Failed to write log: {str(e)}"}

# --- DSN Failure 自動除外エンドポイント ---

DSN_WEBHOOK_SECRET = "lc-dsn-exclude-2026"


@router.post("/sendgrid/dsn-exclude")
async def handle_dsn_exclude(request: Request):
    """
    Google Apps ScriptからDSN Failureのメールアドレスを受信し、
    master_leads.csvに除外フラグを立てる

    期待するJSON:
    {
        "secret": "lc-dsn-exclude-2026",
        "emails": ["chibacari@chibacari.com", "pms@busi-next.com"]
    }
    """
    try:
        data = await request.json()
    except Exception as e:
        return {"status": "error", "message": f"Invalid JSON: {str(e)}"}

    # 簡易認証
    if data.get("secret") != DSN_WEBHOOK_SECRET:
        return {"status": "error", "message": "unauthorized"}

    emails = data.get("emails", [])
    if not emails or not isinstance(emails, list):
        return {"status": "error", "message": "emails list required"}

    flagged = []
    for email in emails:
        email_clean = email.strip().lower()
        if email_clean and "@" in email_clean:
            if _flag_email_in_master(email_clean, "dsn_failure_auto"):
                flagged.append(email_clean)

    return {"status": "ok", "flagged": flagged, "count": len(flagged)}
