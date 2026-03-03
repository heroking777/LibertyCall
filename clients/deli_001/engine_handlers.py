"""後半ステートハンドラ: コース→時間→場所→確認→予約"""
import re
import logging
from typing import List
from datetime import datetime

from .models import (
    State, JST, RESERVATION_API,
    is_yes, is_no, extract_course_minutes, extract_time
)

logger = logging.getLogger("deli_conversation")


def register_handlers(cls):
    """ConversationEngine に後半ハンドラを追加"""

    async def _handle_ask_course(self, text: str) -> List[str]:
        minutes = extract_course_minutes(text)
        if minutes:
            try:
                http = await self._http_session()
                url = (f"{RESERVATION_API}/api/tenants/"
                       f"{self.s.tenant_id}/courses")
                async with http.get(url) as resp:
                    courses = await resp.json()
                matched = next(
                    (c for c in courses
                     if c.get("duration_min") == minutes),
                    None
                )
                if matched:
                    self.s.course_id = matched["id"]
                    self.s.course_name = matched.get(
                        "course_name", f"{minutes}分コース"
                    )
                    self.s.course_minutes = minutes
                else:
                    return [
                        f"{minutes}分のコースはございません。"
                        "60分・90分・120分からお選びください。"
                    ]
            except Exception as e:
                logger.warning(f"course API error: {e}")
                self.s.course_minutes = minutes
                self.s.course_name = f"{minutes}分コース"

            self.s.state = State.ASK_TIME
            return [
                f"{self.s.course_name}ですね。"
                "ご希望のお時間はございますか？"
            ]
        else:
            return [
                "恐れ入りますが、"
                "60分・90分・120分のどちらになさいますか？"
            ]

    async def _handle_ask_time(self, text: str) -> List[str]:
        time_str = extract_time(text)
        if time_str:
            self.s.start_time = time_str
            self.s.state = State.ASK_LOCATION
            return [
                f"{time_str}のご案内ですね。"
                "ご利用場所はどちらになりますか？"
                "ホテル名やご住所をお願いいたします。"
            ]
        else:
            return [
                "恐れ入りますが、ご希望のお時間を"
                "教えていただけますか？"
                "例えば20時、21時半など。"
            ]

    async def _handle_ask_location(self, text: str) -> List[str]:
        if len(text) >= 2:
            self.s.location = text
            self.s.state = State.CONFIRM_ALL
            return [_build_confirmation(self)]
        else:
            return [
                "恐れ入りますが、"
                "ご利用場所を教えていただけますか？"
            ]

    async def _handle_confirm_all(self, text: str) -> List[str]:
        if is_yes(text):
            return await _do_booking(self)
        elif is_no(text):
            return [
                "どちらを変更されますか？"
                "女の子、コース、お時間、場所、"
                "いずれかをおっしゃってください。"
            ]
        elif re.search(r"女の子|キャスト|嬢", text):
            self.s.cast_id = None
            self.s.cast_name = None
            self.s.state = State.ASK_TYPE
            return ["どのようなタイプの女の子がお好みですか？"]
        elif re.search(r"コース|時間.*分", text):
            self.s.state = State.ASK_COURSE
            return [
                "コースはどちらになさいますか？"
                "60分・90分・120分がございます。"
            ]
        elif re.search(r"時間|時", text):
            self.s.state = State.ASK_TIME
            return ["ご希望のお時間を教えていただけますか？"]
        elif re.search(r"場所|ホテル|住所", text):
            self.s.state = State.ASK_LOCATION
            return ["ご利用場所を教えていただけますか？"]
        else:
            return [_build_confirmation(self)]

    async def _handle_booking(self, text: str) -> List[str]:
        return ["ただいまご予約処理中です。少々お待ちください。"]

    async def _handle_done(self, text: str) -> List[str]:
        return [
            "ご予約は完了しております。"
            "他にご質問がございましたらお申し付けください。"
        ]

    async def _handle_error(self, text: str) -> List[str]:
        return [
            "申し訳ございません。"
            "恐れ入りますがもう一度お電話いただけますでしょうか。"
        ]

    # --- ヘルパー ---
    def _build_confirmation(engine) -> str:
        s = engine.s
        return (
            f"ご予約内容の確認です。"
            f"キャスト{s.cast_name}、"
            f"{s.course_name}、"
            f"{s.start_time}に"
            f"{s.location}へのご案内で"
            f"よろしいでしょうか？"
        )

    async def _do_booking(engine) -> List[str]:
        s = engine.s
        s.state = State.BOOKING
        try:
            http = await engine._http_session()
            today = datetime.now(JST).strftime("%Y-%m-%d")
            body = {
                "tenant_id": s.tenant_id,
                "cast_id": s.cast_id,
                "course_id": s.course_id,
                "start_time": f"{today}T{s.start_time}:00+09:00",
                "location": s.location,
                "customer_phone": s.caller_number,
            }
            async with http.post(
                f"{RESERVATION_API}/api/reservations", json=body
            ) as resp:
                if resp.status in (200, 201):
                    result = await resp.json()
                    s.state = State.DONE
                    end_time = result.get("end_time", "")
                    end_hm = ""
                    if "T" in end_time:
                        end_hm = end_time.split("T")[1][:5]
                    return [
                        f"ご予約を承りました。"
                        f"{s.cast_name}が{s.start_time}に"
                        f"{s.location}へお伺いいたします。"
                        f"お時間は{end_hm}までとなります。"
                        f"ありがとうございます。"
                        f"お待ちしております。"
                    ]
                else:
                    err = await resp.text()
                    logger.error(f"booking failed: {resp.status} {err}")
                    s.state = State.CONFIRM_ALL
                    return [
                        "申し訳ございません、"
                        "ご予約の処理中にエラーが発生しました。"
                        "もう一度お試しいただけますか？"
                    ]
        except Exception as e:
            logger.error(f"booking error: {e}")
            s.state = State.CONFIRM_ALL
            return [
                "申し訳ございません、"
                "接続に問題が発生しました。少々お待ちください。"
            ]

    # メソッドをクラスに登録
    cls._handle_ask_course = _handle_ask_course
    cls._handle_ask_time = _handle_ask_time
    cls._handle_ask_location = _handle_ask_location
    cls._handle_confirm_all = _handle_confirm_all
    cls._handle_booking = _handle_booking
    cls._handle_done = _handle_done
    cls._handle_error = _handle_error
    return cls
