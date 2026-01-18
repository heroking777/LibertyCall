"""
MisunderstandingGuard の単体テスト

unclear_streak / not_heard_streak の更新と自動ハンドオフ発火を確認する。
"""

import logging
import pytest
from gateway.core.ai_core import AICore, MisunderstandingGuard, ConversationState

# ログ設定
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

CALL_ID = "test-misunderstanding-guard"


def make_guard():
    """テスト用の MisunderstandingGuard インスタンスを生成"""
    logger = logging.getLogger(__name__)
    return MisunderstandingGuard(logger)


def make_state() -> ConversationState:
    """テスト用の ConversationState を生成"""
    raw = {
        "phase": "QA",
        "last_intent": None,
        "handoff_state": "idle",
        "handoff_retry_count": 0,
        "transfer_requested": False,
        "transfer_executed": False,
        "handoff_prompt_sent": False,
        "not_heard_streak": 0,
        "unclear_streak": 0,
        "handoff_completed": False,
        "last_ai_templates": [],
        "meta": {},
    }
    return ConversationState(raw)


def test_unclear_streak_increment():
    """unclear_streak が 110 テンプレートで増えることを確認"""
    guard = make_guard()
    state = make_state()
    
    # 初期値は 0
    assert state.unclear_streak == 0
    
    # 110 テンプレートで +1
    guard.handle_unclear_streak(CALL_ID, state, ["110"])
    assert state.unclear_streak == 1
    
    # もう一度 110 で +1
    guard.handle_unclear_streak(CALL_ID, state, ["110"])
    assert state.unclear_streak == 2


def test_unclear_streak_reset_on_normal_template():
    """通常のテンプレートで unclear_streak がリセットされることを確認"""
    guard = make_guard()
    state = make_state()
    
    # まず 110 で増やす
    guard.handle_unclear_streak(CALL_ID, state, ["110"])
    assert state.unclear_streak == 1
    
    # 通常のテンプレート（006）でリセット
    guard.handle_unclear_streak(CALL_ID, state, ["006"])
    assert state.unclear_streak == 0


def test_auto_handoff_from_unclear_streak():
    """unclear_streak >= 2 で自動ハンドオフ発火することを確認"""
    guard = make_guard()
    state = make_state()
    state.unclear_streak = 2
    state.handoff_state = "idle"
    
    intent, triggered = guard.check_auto_handoff_from_unclear(CALL_ID, state, "UNKNOWN")
    
    assert triggered is True
    assert intent == "HANDOFF_REQUEST"
    assert state.meta.get("reason_for_handoff") == "auto_unclear"
    assert state.meta.get("unclear_streak_at_trigger") == 2


def test_auto_handoff_not_triggered_when_handoff_state_confirming():
    """handoff_state=confirming の場合は自動ハンドオフ発火しないことを確認"""
    guard = make_guard()
    state = make_state()
    state.unclear_streak = 2
    state.handoff_state = "confirming"
    
    intent, triggered = guard.check_auto_handoff_from_unclear(CALL_ID, state, "UNKNOWN")
    
    assert triggered is False
    assert intent == "UNKNOWN"


def test_not_heard_streak_increment():
    """not_heard_streak が 110 テンプレートで増えることを確認"""
    guard = make_guard()
    state = make_state()
    
    # 初期値は 0
    assert state.not_heard_streak == 0
    
    # 110 テンプレートで +1
    template_ids, intent, should_return = guard.handle_not_heard_streak(
        CALL_ID, state, ["110"], "UNKNOWN", "UNKNOWN"
    )
    assert state.not_heard_streak == 1
    assert should_return is False
    
    # もう一度 110 で +1 → 2回目で 0604 に切り替え
    template_ids, intent, should_return = guard.handle_not_heard_streak(
        CALL_ID, state, ["110"], "UNKNOWN", "UNKNOWN"
    )
    assert state.not_heard_streak == 0  # リセットされる
    assert template_ids == ["0604"]
    assert state.handoff_state == "confirming"
    assert should_return is True


def test_not_heard_streak_reset_on_normal_template():
    """通常のテンプレートで not_heard_streak がリセットされることを確認"""
    guard = make_guard()
    state = make_state()
    
    # まず 110 で増やす
    template_ids, intent, should_return = guard.handle_not_heard_streak(
        CALL_ID, state, ["110"], "UNKNOWN", "UNKNOWN"
    )
    assert state.not_heard_streak == 1
    
    # 通常のテンプレート（006）でリセット
    template_ids, intent, should_return = guard.handle_not_heard_streak(
        CALL_ID, state, ["006"], "UNKNOWN", "UNKNOWN"
    )
    assert state.not_heard_streak == 0
    assert should_return is False


def test_reset_unclear_streak_on_handoff_done():
    """handoff_done 時に unclear_streak がリセットされることを確認"""
    guard = make_guard()
    state = make_state()
    state.unclear_streak = 3
    
    guard.reset_unclear_streak_on_handoff_done(CALL_ID, state, "handoff_done")
    
    assert state.unclear_streak == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

