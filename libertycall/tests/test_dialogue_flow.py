"""
対話フロー方式のテスト

フェーズ1: 料金の聞き返しパターンをテスト
"""

import pytest
from libertycall.gateway.dialogue_flow import (
    get_response,
    is_ambiguous_price_question,
    check_clear_price_question,
    handle_price_type_response,
    is_handoff_request,
    is_end_call,
    is_not_heard,
)


class TestPriceQuestions:
    """料金関連の質問テスト"""

    def test_ambiguous_price_question(self):
        """曖昧な料金質問 → 聞き返し"""
        test_cases = [
            "料金教えて",
            "いくらですか？",
            "値段は？",
            "費用はどれくらい？",
        ]
        for text in test_cases:
            assert is_ambiguous_price_question(text), f"Failed: {text}"
            
            template_ids, phase, state = get_response(text, "QA")
            assert template_ids == ["115"], f"Failed template for: {text}"
            assert phase == "WAITING_PRICE_TYPE", f"Failed phase for: {text}"
            assert state.get("waiting_retry_count") == 0

    def test_clear_price_questions(self):
        """明確な料金質問 → 即答"""
        test_cases = [
            ("月額いくらですか？", ["040"]),
            ("初期費用はかかりますか？", ["042"]),
            ("通話料は？", ["116"]),
            ("最低契約期間は？", ["045"]),
            ("解約料は？", ["046"]),
        ]
        for text, expected in test_cases:
            result = check_clear_price_question(text)
            assert result == expected, f"Failed for: {text}"
            
            template_ids, phase, state = get_response(text, "QA")
            assert template_ids == expected, f"Failed template for: {text}"
            assert phase == "QA"

    def test_price_type_response_monthly(self):
        """WAITING_PRICE_TYPE で「月額」と答える"""
        template_ids, phase, state = handle_price_type_response("月額", {})
        assert template_ids == ["040"]
        assert phase == "QA"

    def test_price_type_response_initial(self):
        """WAITING_PRICE_TYPE で「初期費用」と答える"""
        template_ids, phase, state = handle_price_type_response("初期費用", {})
        assert template_ids == ["042"]
        assert phase == "QA"

    def test_price_type_response_call_charge(self):
        """WAITING_PRICE_TYPE で「通話料」と答える"""
        template_ids, phase, state = handle_price_type_response("通話料", {})
        assert template_ids == ["116"]
        assert phase == "QA"

    def test_price_type_response_all(self):
        """WAITING_PRICE_TYPE で「全部」と答える"""
        template_ids, phase, state = handle_price_type_response("全部", {})
        assert template_ids == ["122"]
        assert phase == "QA"

    def test_price_type_response_unknown(self):
        """WAITING_PRICE_TYPE で「わからない」と答える"""
        template_ids, phase, state = handle_price_type_response("わからない", {})
        assert template_ids == ["122"]
        assert phase == "QA"

    def test_price_type_response_invalid_retry(self):
        """WAITING_PRICE_TYPE で意味不明な回答 → もう一度聞く"""
        # 1回目
        template_ids, phase, state = handle_price_type_response("バナナ", {"waiting_retry_count": 0})
        assert template_ids == ["115"], "1回目は聞き返し"
        assert phase == "WAITING_PRICE_TYPE"
        assert state.get("waiting_retry_count") == 1
        
        # 2回目
        template_ids, phase, state = handle_price_type_response("バナナ", {"waiting_retry_count": 1})
        assert template_ids == ["0604"], "2回目はハンドオフ"
        assert phase == "HANDOFF_CONFIRM_WAIT"


class TestPriorityRules:
    """優先順位ルールのテスト"""

    def test_handoff_during_waiting(self):
        """WAITING_PRICE_TYPE 中にハンドオフ要求 → 即ハンドオフ"""
        template_ids, phase, state = get_response("担当者に代わって", "WAITING_PRICE_TYPE")
        assert template_ids == ["0604"]
        assert phase == "HANDOFF_CONFIRM_WAIT"

    def test_end_call_during_waiting(self):
        """WAITING_PRICE_TYPE 中に終了 → 即終了"""
        template_ids, phase, state = get_response("ありがとうございました", "WAITING_PRICE_TYPE")
        assert template_ids == ["086"]
        assert phase == "END"

    def test_clear_question_during_waiting(self):
        """WAITING_PRICE_TYPE 中に明確な質問 → Phase無視して即答"""
        template_ids, phase, state = get_response("途中で話しても大丈夫？", "WAITING_PRICE_TYPE")
        assert template_ids == ["065"]
        assert phase == "QA"


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_silence_first(self):
        """無音（1回目）→ 催促"""
        template_ids, phase, state = get_response("", "QA")
        assert template_ids == ["110"]
        assert phase == "QA"
        assert state.get("silence_count") == 1

    def test_silence_second(self):
        """無音（2回目）→ ハンドオフ"""
        template_ids, phase, state = get_response("", "QA", {"silence_count": 1})
        assert template_ids == ["0604"]
        assert phase == "HANDOFF_CONFIRM_WAIT"

    def test_not_heard(self):
        """聞き取れない発話 → 聞き返し"""
        template_ids, phase, state = get_response("ゴニョゴニョ", "QA")
        assert template_ids == ["0602"]
        assert phase == "QA"

    def test_greeting(self):
        """挨拶 → 挨拶応答"""
        template_ids, phase, state = get_response("もしもし", "QA")
        assert template_ids == ["004"]
        assert phase == "QA"

    def test_unknown(self):
        """どれにも該当しない → UNKNOWN"""
        template_ids, phase, state = get_response("あいうえお", "QA")
        assert template_ids == ["114"]
        assert phase == "QA"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

