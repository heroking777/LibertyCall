"""Intent classification helpers extracted from AICore."""

from __future__ import annotations

from typing import Optional


def classify_simple_intent(text: str, normalized: str) -> Optional[str]:
    """Simple YES/NO/OTHER intent classification."""
    yes_keywords = ["はい", "ええ", "うん", "そうです", "そう", "了解", "りょうかい", "ok", "okです"]
    if any(kw in normalized for kw in yes_keywords):
        return "YES"

    no_keywords = ["いいえ", "いえ", "違います", "ちがいます", "違う", "ちがう", "no", "ノー"]
    if any(kw in normalized for kw in no_keywords):
        return "NO"

    return None
