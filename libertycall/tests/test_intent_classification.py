"""
Intent分類とテンプレート選択の自動テスト

INTENT_TEST_CASES.md の質問リストを基に、
各Intentが正しく分類され、期待されるテンプレートIDが返ることを確認する。
"""

import pytest
from libertycall.gateway.intent_rules import classify_intent, select_template_ids


class TestIntentClassification:
    """Intent分類のテストクラス"""

    def test_not_heard(self):
        """NOT_HEARD Intentのテスト"""
        test_cases = [
            "ゴニョゴニョ",
            "あー、えー、うー",
            "###",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "NOT_HEARD", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["0602"], f"Failed template for: {text}"

    def test_greeting(self):
        """GREETING Intentのテスト"""
        test_cases = [
            "もしもし",
            "こんにちは",
            "お世話になります",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "GREETING", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["004"], f"Failed template for: {text}"

    def test_inquiry(self):
        """INQUIRY Intentのテスト（修正後: すべて006のみ）"""
        test_cases = [
            "ホームページを見て電話しました",
            "導入を検討しています",
            "サービスについて教えてください",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            # SYSTEM_INQUIRYになる場合もあるので、INQUIRYまたはSYSTEM_INQUIRY
            assert intent in ["INQUIRY", "SYSTEM_INQUIRY"], f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: INQUIRYはすべて["006"]のみ
            if intent == "INQUIRY":
                assert template_ids == ["006"], f"Failed template for: {text}"

    def test_price(self):
        """PRICE Intentのテスト（修正後: すべて040のみ）"""
        test_cases = [
            "料金はいくらですか？",
            "初期費用はかかりますか？",
            "月額いくらですか？",
            "解約料はありますか？",
            "トライアルはありますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "PRICE", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: PRICEはすべて["040"]のみ
            assert template_ids == ["040"], f"Failed template for: {text}"

    def test_function(self):
        """FUNCTION Intentのテスト（修正後: すべて023のみ）"""
        test_cases = [
            "どんな機能がありますか？",
            "セキュリティは大丈夫ですか？",
            "転送機能はありますか？",
            "間違った案内をしませんか？",
            "録音データはどうなりますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "FUNCTION", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: FUNCTIONはすべて["023"]のみ
            assert template_ids == ["023"], f"Failed template for: {text}"

    def test_setup(self):
        """SETUP Intentのテスト（修正後: すべて060のみ）"""
        test_cases = [
            "すぐに使えますか？",
            "いつから使えますか？",
            "どうやって導入しますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "SETUP", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: SETUPはすべて["060"]のみ
            assert template_ids == ["060"], f"Failed template for: {text}"

    def test_system_explain(self):
        """SYSTEM_EXPLAIN Intentのテスト（修正後: 4つ→1つ）"""
        test_cases = [
            "どういうシステムですか？",
            "どんなシステムなの？",
            "システムの仕組みを教えて",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "SYSTEM_EXPLAIN", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: SYSTEM_EXPLAINは["020"]のみ
            assert template_ids == ["020"], f"Failed template for: {text}"

    def test_handoff_yes(self):
        """HANDOFF_YES Intentのテスト（修正後: 空リスト→明示的）"""
        # 注意: HANDOFF_YESはcontext="handoff_confirming"が必要
        # ここでは直接select_template_idsのテストのみ
        intent = "HANDOFF_YES"
        text = "はい"
        
        template_ids = select_template_ids(intent, text)
        # 修正後: HANDOFF_YESは["081", "082"]
        assert template_ids == ["081", "082"], f"Failed template for: {text}"

    def test_handoff_no(self):
        """HANDOFF_NO Intentのテスト（修正後: 空リスト→明示的）"""
        intent = "HANDOFF_NO"
        text = "いいえ"
        
        template_ids = select_template_ids(intent, text)
        # 修正後: HANDOFF_NOは["086", "087"]
        assert template_ids == ["086", "087"], f"Failed template for: {text}"

    def test_handoff_request(self):
        """HANDOFF_REQUEST Intentのテスト（修正後: 空リスト→明示的）"""
        test_cases = [
            "担当者と話したい",
            "詳しい人に代わってください",
            "人間と話せますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "HANDOFF_REQUEST", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: HANDOFF_REQUESTは["0604"]
            assert template_ids == ["0604"], f"Failed template for: {text}"

    def test_end_call(self):
        """END_CALL Intentのテスト（修正後: 3つ→1つ）"""
        test_cases = [
            "もう大丈夫です",
            "ありがとうございました",
            "結構です",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "END_CALL", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: END_CALLは["086"]のみ
            assert template_ids == ["086"], f"Failed template for: {text}"

    def test_reservation(self):
        """RESERVATION Intentのテスト（修正後: 常に2つ→1つ、085削除）"""
        test_cases = [
            "予約機能はありますか？",
            "ダブルブッキングは防げますか？",
            "予約のキャンセルはできますか？",
            "席の予約管理はできますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "RESERVATION", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: RESERVATIONは["070"]のみ
            assert template_ids == ["070"], f"Failed template for: {text}"

    def test_multi_store(self):
        """MULTI_STORE Intentのテスト（修正後: 2つ→1つ、085削除）"""
        test_cases = [
            "複数店舗で使えますか？",
            "店舗がいくつかあるんですが",
            "別店舗でも使えますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "MULTI_STORE", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: MULTI_STOREは["069"]のみ
            assert template_ids == ["069"], f"Failed template for: {text}"

    def test_dialect(self):
        """DIALECT Intentのテスト（修正後: 2つ→1つ、085削除）"""
        test_cases = [
            "関西弁で話せますか？",
            "方言に対応してますか？",
            "イントネーションは？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "DIALECT", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: DIALECTは["066"]のみ
            assert template_ids == ["066"], f"Failed template for: {text}"

    def test_interrupt(self):
        """INTERRUPT Intentのテスト（修正後: 2つ→1つ、085削除）"""
        test_cases = [
            "途中で話しても大丈夫？",
            "割り込んでもいいですか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "INTERRUPT", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: INTERRUPTは["065"]のみ
            assert template_ids == ["065"], f"Failed template for: {text}"

    def test_busy(self):
        """BUSY Intentのテスト（修正後: 2つ→1つ）"""
        test_cases = [
            "混んでますか？",
            "混んでる？",
            "込み合ってますか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "BUSY", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # 修正後: BUSYは["090"]のみ
            assert template_ids == ["090"], f"Failed template for: {text}"

    def test_unknown(self):
        """UNKNOWN Intentのテスト"""
        test_cases = [
            "あいうえお",
            "意味不明な文章",
            "12345",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "UNKNOWN", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # UNKNOWNは["114"]
            assert template_ids == ["114"], f"Failed template for: {text}"

    def test_system_inquiry(self):
        """SYSTEM_INQUIRY Intentのテスト"""
        test_cases = [
            "システムについて聞きたい",
            "システムの使い方を教えて",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "SYSTEM_INQUIRY", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            # SYSTEM_INQUIRYは["006_SYS"]
            assert template_ids == ["006_SYS"], f"Failed template for: {text}"

    def test_ai_call_topic(self):
        """AI_CALL_TOPIC Intentのテスト"""
        test_cases = [
            "AI電話の件で",
            "AIの電話について",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "AI_CALL_TOPIC", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["0600"], f"Failed template for: {text}"

    def test_ai_identity(self):
        """AI_IDENTITY Intentのテスト"""
        test_cases = [
            "あなたはAIですか？",
            "AIがやってるんですか？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "AI_IDENTITY", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["023_AI_IDENTITY"], f"Failed template for: {text}"

    def test_callback_request(self):
        """CALLBACK_REQUEST Intentのテスト"""
        test_cases = [
            "折り返してください",
            "かけ直してください",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "CALLBACK_REQUEST", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["0601"], f"Failed template for: {text}"

    def test_setup_difficulty(self):
        """SETUP_DIFFICULTY Intentのテスト"""
        test_cases = [
            "設定は難しいですか？",
            "設定むずい？",
        ]
        for text in test_cases:
            intent = classify_intent(text)
            assert intent == "SETUP_DIFFICULTY", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["0603"], f"Failed template for: {text}"

    def test_support(self):
        """SUPPORT Intentのテスト（条件分岐あり）"""
        # 不具合系
        test_cases_bug = [
            "不具合があったらどうしますか？",
            "故障した場合は？",
        ]
        for text in test_cases_bug:
            intent = classify_intent(text)
            assert intent == "SUPPORT", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["0285"], f"Failed template for: {text}"
        
        # その他
        test_cases_general = [
            "サポートはありますか？",
        ]
        for text in test_cases_general:
            intent = classify_intent(text)
            assert intent == "SUPPORT", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["0284"], f"Failed template for: {text}"

    def test_sales_call(self):
        """SALES_CALL Intentのテスト（条件分岐あり）"""
        # 営業と明示
        test_cases_sales = [
            "営業の電話です",
            "はい営業です",
        ]
        for text in test_cases_sales:
            intent = classify_intent(text)
            assert intent == "SALES_CALL", f"Failed for: {text}"
            
            template_ids = select_template_ids(intent, text)
            assert template_ids == ["094", "088"], f"Failed template for: {text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

