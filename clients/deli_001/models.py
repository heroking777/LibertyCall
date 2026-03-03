"""定義・ヘルパー関数・Sessionデータクラス"""
import re
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("deli_conversation")
JST = timezone(timedelta(hours=9))
RESERVATION_API = "http://localhost:8100"


class State(str, Enum):
    INIT = "init"
    GREETING = "greeting"
    CONFIRM_REPEAT_CAST = "confirm_repeat_cast"
    ASK_TYPE = "ask_type"
    SUGGEST_CAST = "suggest_cast"
    SUGGEST_ALT = "suggest_alt"
    ASK_COURSE = "ask_course"
    ASK_TIME = "ask_time"
    ASK_LOCATION = "ask_location"
    CONFIRM_ALL = "confirm_all"
    BOOKING = "booking"
    DONE = "done"
    ERROR = "error"


YES_RE = re.compile(
    r"(はい|うん|ええ|お願い|それで|いいよ|いいです|大丈夫|オッケー|OK"
    r"|そうで|そうし|頼む|頼みます|よろしく)", re.IGNORECASE
)
NO_RE = re.compile(
    r"(いいえ|いや[^し]?|違う|ちがう|ちょっと|別の|他の|変えて"
    r"|やめ|いらない|だめ|ダメ|no)", re.IGNORECASE
)


def is_yes(t: str) -> bool:
    return bool(YES_RE.search(t))

def is_no(t: str) -> bool:
    return bool(NO_RE.search(t))

def extract_time(t: str) -> Optional[str]:
    if re.search(r"今から|すぐ|最短|できるだけ早", t):
        now = datetime.now(JST) + timedelta(minutes=30)
        now = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
        return now.strftime("%H:%M")
    m = re.search(r"(\d{1,2})\s*時\s*半", t)
    if m:
        return f"{int(m.group(1)):02d}:30"
    m = re.search(r"(\d{1,2})\s*[時じ:]\s*(\d{1,2})?\s*[分ふん]?", t)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if 0 <= h <= 29 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    return None

def extract_course_minutes(t: str) -> Optional[int]:
    m = re.search(r"(\d{2,3})\s*(分|ふん|min)", t)
    if m:
        return int(m.group(1))
    if re.search(r"ショート", t):
        return 60
    if re.search(r"ロング|長い", t):
        return 120
    if re.search(r"基本|スタンダード|普通", t):
        return 90
    return None


@dataclass
class Session:
    call_uuid: str
    tenant_id: str
    caller_number: str
    state: State = State.INIT
    is_repeater: bool = False
    cast_id: Optional[str] = None
    cast_name: Optional[str] = None
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    course_minutes: Optional[int] = None
    start_time: Optional[str] = None
    location: Optional[str] = None
    suggestion: Optional[Dict[str, Any]] = None
    history: list = field(default_factory=list)

    def log(self, role: str, text: str):
        self.history.append({
            "role": role, "text": text,
            "state": self.state.value,
            "ts": datetime.now(JST).isoformat()
        })
