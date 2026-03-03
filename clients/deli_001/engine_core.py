"""会話エンジン本体 - start() と前半ステートハンドラ"""
import re
import logging
import aiohttp
from typing import Optional, List
from datetime import datetime, timedelta

from .models import (
    State, Session, JST, RESERVATION_API,
    is_yes, is_no, extract_course_minutes, extract_time
)

logger = logging.getLogger("deli_conversation")


class ConversationEngine:

    def __init__(self, session: Session):
        self.s = session
        self._http: Optional[aiohttp.ClientSession] = None

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def close(self):
        if self._http and not self._http.closed:
            await self._http.close()

    def _default_start_time(self) -> str:
        """現在時刻から30分後を仮のstart_timeとして返す"""
        now = datetime.now(JST) + timedelta(minutes=30)
        now = now.replace(
            minute=(now.minute // 30) * 30,
            second=0, microsecond=0
        )
        return now.strftime("%Y-%m-%dT%H:%M:%S+09:00")

    def _default_course_id(self) -> str:
        """デフォルトコース（60分）のIDを返す"""
        return "f65bf8ed-2da4-4f84-a37b-546b20e0fb93"

    async def _call_suggest(
        self,
        course_id: Optional[str] = None,
        start_time: Optional[str] = None
    ) -> Optional[dict]:
        """suggest APIを呼ぶ共通メソッド"""
        try:
            http = await self._http_session()
            params = {
                "tenant_id": self.s.tenant_id,
                "phone_number": self.s.caller_number,
                "course_id": course_id or self.s.course_id
                    or self._default_course_id(),
                "start_time": start_time
                    or self._build_start_time()
                    or self._default_start_time(),
            }
            async with http.get(
                f"{RESERVATION_API}/api/suggest", params=params
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    body = await resp.text()
                    logger.warning(
                        f"suggest API {resp.status}: {body}"
                    )
                    return None
        except Exception as e:
            logger.warning(f"suggest API error: {e}")
            return None

    def _build_start_time(self) -> Optional[str]:
        """セッションのstart_timeからISO形式を組み立て"""
        if self.s.start_time:
            today = datetime.now(JST).strftime("%Y-%m-%d")
            return f"{today}T{self.s.start_time}:00+09:00"
        return None

    # === 着信エントリ ===
    async def start(self) -> List[str]:
        self.s.state = State.GREETING
        greeting = (
            "お電話ありがとうございます。"
            "デリバリーヘルスでございます。"
        )

        # suggest APIでリピーター判定
        data = await self._call_suggest()
        if data:
            self.s.is_repeater = data.get("is_repeater", False)
            self.s.suggestion = data

        if self.s.is_repeater and self.s.suggestion:
            primary = self.s.suggestion.get("primary", {})
            p_name = primary.get("display_name", "")
            p_id = primary.get("cast_id") or primary.get("id")
            stype = self.s.suggestion.get("type", "")

            if stype == "repeater_available" and p_id:
                self.s.cast_id = p_id
                self.s.cast_name = p_name
                self.s.state = State.CONFIRM_REPEAT_CAST
                replies = [
                    greeting,
                    f"いつもありがとうございます。"
                    f"前回ご利用の{p_name}、"
                    f"本日も出勤しておりますが"
                    f"いかがでしょうか？"
                ]
            elif stype == "repeater_busy":
                alts = self.s.suggestion.get("alternatives", [])
                alt = alts[0] if alts else {}
                alt_name = alt.get("display_name", "")
                alt_id = alt.get("cast_id") or alt.get("id")
                if alt_id:
                    self.s.cast_id = alt_id
                    self.s.cast_name = alt_name
                    self.s.state = State.SUGGEST_CAST
                    replies = [
                        greeting,
                        f"いつもありがとうございます。"
                        f"前回の{p_name}は"
                        f"現在ご案内中でございます。"
                        f"{alt_name}はいかがでしょうか？"
                    ]
                else:
                    self.s.state = State.ASK_TYPE
                    replies = [
                        greeting,
                        f"いつもありがとうございます。"
                        f"前回の{p_name}は"
                        f"本日出勤しておりません。"
                        f"どのようなタイプの女の子が"
                        f"お好みですか？"
                    ]
            else:
                self.s.state = State.ASK_TYPE
                replies = [
                    greeting,
                    "いつもありがとうございます。"
                    "どのようなタイプの女の子が"
                    "お好みですか？"
                ]
        else:
            self.s.state = State.ASK_TYPE
            replies = [
                greeting,
                "ご利用ありがとうございます。"
                "どのようなタイプの女の子がお好みですか？"
                "例えばスレンダー系、グラマー系など"
                "お気軽にお申し付けください。"
            ]

        for r in replies:
            self.s.log("assistant", r)
        return replies

    # === メインディスパッチ ===
    async def on_transcript(self, text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []
        self.s.log("user", text)
        handler = getattr(
            self, f"_handle_{self.s.state.value}", None
        )
        if not handler:
            return [
                "申し訳ございません、"
                "もう一度お願いできますか？"
            ]
        replies = await handler(text)
        for r in replies:
            self.s.log("assistant", r)
        return replies

    # === リピーター前回キャスト確認 ===
    async def _handle_confirm_repeat_cast(
        self, text: str
    ) -> List[str]:
        if is_yes(text):
            self.s.state = State.ASK_COURSE
            return [
                f"{self.s.cast_name}でご案内いたしますね。"
                "コースはいかがなさいますか？"
                "60分・90分・120分がございます。"
            ]
        elif is_no(text):
            self.s.cast_id = None
            self.s.cast_name = None
            self.s.state = State.ASK_TYPE
            return [
                "かしこまりました。"
                "どのようなタイプの女の子がお好みですか？"
            ]
        else:
            return [
                f"前回の{self.s.cast_name}で"
                f"よろしいですか？"
            ]

    # === 新規: タイプ → 提案 ===
    async def _handle_ask_type(
        self, text: str
    ) -> List[str]:
        return await self._do_suggest()

    async def _do_suggest(self) -> List[str]:
        self.s.state = State.SUGGEST_CAST
        data = await self._call_suggest()
        if data:
            self.s.suggestion = data
            primary = data.get("primary")
            if primary:
                self.s.cast_id = (
                    primary.get("cast_id")
                    or primary.get("id")
                )
                self.s.cast_name = primary.get(
                    "display_name", ""
                )
                msg = data.get(
                    "message",
                    f"本日は{self.s.cast_name}が"
                    f"おすすめでございます。"
                )
                return [f"{msg}いかがでしょうか？"]

        self.s.state = State.ERROR
        return [
            "申し訳ございません、"
            "現在ご案内可能なキャストがおりません。"
            "お時間を変えてお電話いただけますでしょうか。"
        ]

    # === キャスト提案応答 ===
    async def _handle_suggest_cast(
        self, text: str
    ) -> List[str]:
        if is_yes(text):
            self.s.state = State.ASK_COURSE
            return [
                f"{self.s.cast_name}でご案内いたしますね。"
                "コースはいかがなさいますか？"
                "60分・90分・120分がございます。"
            ]
        elif is_no(text) or re.search(r"別|他|違う", text):
            alts = (
                self.s.suggestion.get("alternatives", [])
                if self.s.suggestion else []
            )
            alt = alts[0] if alts else {}
            alt_id = alt.get("cast_id") or alt.get("id")
            if alt_id:
                self.s.cast_id = alt_id
                self.s.cast_name = alt.get(
                    "display_name", ""
                )
                self.s.state = State.SUGGEST_ALT
                return [
                    f"では{self.s.cast_name}は"
                    f"いかがでしょうか？"
                ]
            else:
                return [
                    "申し訳ございません、"
                    "他にご案内可能な子がおりません。"
                    f"{self.s.cast_name}でよろしいですか？"
                ]
        else:
            return [f"{self.s.cast_name}でよろしいですか？"]

    async def _handle_suggest_alt(
        self, text: str
    ) -> List[str]:
        if is_yes(text):
            self.s.state = State.ASK_COURSE
            return [
                f"{self.s.cast_name}でご案内いたしますね。"
                "コースはいかがなさいますか？"
                "60分・90分・120分がございます。"
            ]
        elif is_no(text):
            self.s.state = State.ERROR
            return [
                "申し訳ございません、"
                "ただいまご案内可能なキャストが"
                "おりません。"
                "お時間を変えてお電話いただけますでしょうか。"
            ]
        else:
            return [f"{self.s.cast_name}でよろしいですか？"]
