"""
対話フロー方式の応答判定ロジック

Intent方式の複雑さを排除し、自然な会話フローで誤案内ゼロを実現。
基本原則: 曖昧な質問には聞き返す。明確な質問には即答する。
"""

import logging
from typing import Tuple, Dict, List, Optional

logger = logging.getLogger(__name__)


# ========================================
# ユーティリティ関数
# ========================================

def contains_any(text: str, keywords: list[str]) -> bool:
    """テキストに指定されたキーワードのいずれかが含まれているかチェック"""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in keywords)


def is_silence(text: str) -> bool:
    """無音（空文字列または空白のみ）かチェック"""
    return not text or text.strip() == ""


# ========================================
# 最優先判定（Phaseに関係なく処理）
# ========================================

def is_handoff_request(text: str) -> bool:
    """ハンドオフ要求の判定"""
    keywords = [
        "担当者", "人間", "代わって", "電話代わって", "つないで",
        "詳しい人", "詳しい方", "スタッフ", "オペレーター"
    ]
    return contains_any(text, keywords)


def is_end_call(text: str) -> bool:
    """通話終了の判定"""
    keywords = [
        "ありがとうございました", "ありがとう", "結構です",
        "大丈夫です", "もう大丈夫", "それで大丈夫"
    ]
    return contains_any(text, keywords)


def is_not_heard(text: str) -> bool:
    """聞き取れない発話の判定"""
    # ゴニョゴニョ
    if "ゴニョゴニョ" in text:
        return True
    
    # 特殊文字が3つ以上
    special_chars = ["…", "。", "、", ".", ","]
    count = sum(text.count(char) for char in special_chars)
    return count >= 3


def is_greeting(text: str) -> bool:
    """挨拶の判定"""
    keywords = ["もしもし", "こんにちは", "おはよう", "こんばんは"]
    return contains_any(text, keywords)


# ========================================
# 料金関連の判定
# ========================================

def is_ambiguous_price_question(text: str) -> bool:
    """曖昧な料金質問の判定（聞き返しが必要）"""
    # 料金関連のキーワードはあるが、具体的な種類が指定されていない
    price_keywords = ["料金", "いくら", "値段", "金額", "費用", "コスト"]
    specific_keywords = ["初期", "月額", "通話", "解約", "契約"]
    
    has_price_keyword = contains_any(text, price_keywords)
    has_specific_keyword = contains_any(text, specific_keywords)
    
    return has_price_keyword and not has_specific_keyword


def check_clear_price_question(text: str) -> Optional[List[str]]:
    """明確な料金質問の判定（即答）"""
    # 月額
    if "月額" in text:
        return ["040"]
    
    # 初期費用
    if contains_any(text, ["初期費用", "初期コスト", "初期"]):
        return ["042"]
    
    # 通話料
    if "通話" in text and contains_any(text, ["料", "費用", "コスト"]):
        return ["116"]
    
    # 最低契約期間
    if contains_any(text, ["最低契約", "契約期間"]):
        return ["045"]
    
    # 解約料
    if "解約" in text:
        return ["046"]
    
    return None


def handle_price_type_response(text: str, state: Dict) -> Tuple[List[str], str, Dict]:
    """
    WAITING_PRICE_TYPE でのユーザー回答処理
    
    Returns:
        (template_ids, new_phase, updated_state)
    """
    # "わからない" "全部" → 全体説明
    if contains_any(text, ["わからない", "全部", "全て", "すべて"]):
        logger.info("PRICE_TYPE: わからない/全部 → 全体説明")
        return (["122"], "QA", {})
    
    # "初期費用" → 042
    if contains_any(text, ["初期", "初期費用"]):
        logger.info("PRICE_TYPE: 初期費用 → 042")
        return (["042"], "QA", {})
    
    # "通話料" → 116
    if "通話" in text:
        logger.info("PRICE_TYPE: 通話料 → 116")
        return (["116"], "QA", {})
    
    # "月額" → 040
    if "月額" in text:
        logger.info("PRICE_TYPE: 月額 → 040")
        return (["040"], "QA", {})
    
    # 意味不明な回答 → もう一度聞く or ハンドオフ
    retry_count = state.get("waiting_retry_count", 0)
    if retry_count == 0:
        # 1回目: もう一度聞く
        logger.warning(f"PRICE_TYPE: 意味不明な回答（1回目）: {text}")
        return (["115"], "WAITING_PRICE_TYPE", {"waiting_retry_count": 1})
    else:
        # 2回目: 諦めてハンドオフ
        logger.warning(f"PRICE_TYPE: 意味不明な回答（2回目）→ ハンドオフ: {text}")
        return (["0604"], "HANDOFF_CONFIRM_WAIT", {})


# ========================================
# 機能関連の判定
# ========================================

def is_ambiguous_function_question(text: str) -> bool:
    """曖昧な機能質問の判定（聞き返しが必要）"""
    # 機能関連のキーワードはあるが、具体的な種類が指定されていない
    function_keywords = ["機能", "できる", "何ができ", "どんなこと"]
    specific_keywords = [
        "割り込", "途中で話", "口挟",
        "営業電話", "営業",
        "転送", "引継",
        "24時間", "夜間",
        "方言", "関西弁",
        "セキュリティ", "個人情報"
    ]
    
    has_function_keyword = contains_any(text, function_keywords)
    has_specific_keyword = contains_any(text, specific_keywords)
    
    return has_function_keyword and not has_specific_keyword


def handle_function_type_response(text: str, state: Dict) -> Tuple[List[str], str, Dict]:
    """
    WAITING_FUNCTION_TYPE でのユーザー回答処理
    
    Returns:
        (template_ids, new_phase, updated_state)
    """
    # "わからない" "全部" "その他" → 全体説明
    if contains_any(text, ["わからない", "全部", "全て", "すべて", "その他"]):
        logger.info("FUNCTION_TYPE: わからない/全部/その他 → 全体説明")
        return (["119"], "QA", {})
    
    # "割り込み" "途中で話す" → 065
    if contains_any(text, ["割り込", "途中で話", "口挟"]):
        logger.info("FUNCTION_TYPE: 割り込み → 065")
        return (["065"], "QA", {})
    
    # "営業電話" → 118
    if contains_any(text, ["営業", "営業電話"]):
        logger.info("FUNCTION_TYPE: 営業電話 → 118")
        return (["118"], "QA", {})
    
    # "転送" → 023
    if contains_any(text, ["転送", "引継"]):
        logger.info("FUNCTION_TYPE: 転送 → 023")
        return (["023"], "QA", {})
    
    # "24時間" → 121
    if contains_any(text, ["24時間", "夜間", "休日"]):
        logger.info("FUNCTION_TYPE: 24時間 → 121")
        return (["121"], "QA", {})
    
    # "方言" → 066
    if contains_any(text, ["方言", "関西弁", "イントネーション"]):
        logger.info("FUNCTION_TYPE: 方言 → 066")
        return (["066"], "QA", {})
    
    # "セキュリティ" → 063
    if contains_any(text, ["セキュリティ", "個人情報", "録音"]):
        logger.info("FUNCTION_TYPE: セキュリティ → 063")
        return (["063"], "QA", {})
    
    # 意味不明な回答 → もう一度聞く or ハンドオフ
    retry_count = state.get("waiting_retry_count", 0)
    if retry_count == 0:
        # 1回目: もう一度聞く
        logger.warning(f"FUNCTION_TYPE: 意味不明な回答（1回目）: {text}")
        return (["117"], "WAITING_FUNCTION_TYPE", {"waiting_retry_count": 1})
    else:
        # 2回目: 諦めてハンドオフ
        logger.warning(f"FUNCTION_TYPE: 意味不明な回答（2回目）→ ハンドオフ: {text}")
        return (["0604"], "HANDOFF_CONFIRM_WAIT", {})


# ========================================
# その他の明確な質問判定
# ========================================

def check_clear_questions(text: str) -> Optional[List[str]]:
    """
    明確な質問の判定（即答可能）
    
    Returns:
        template_ids or None
    """
    # 挨拶
    if is_greeting(text):
        return ["004"]
    
    # 料金関連
    price_response = check_clear_price_question(text)
    if price_response:
        return price_response
    
    # 機能関連
    if contains_any(text, ["途中で話", "割り込", "口挟"]):
        return ["065"]
    
    if contains_any(text, ["関西弁", "方言", "イントネーション"]):
        return ["066"]
    
    if contains_any(text, ["24時間", "夜間", "休日"]):
        return ["121"]
    
    if "転送" in text or "引継" in text:
        return ["023"]
    
    if contains_any(text, ["セキュリティ", "個人情報", "録音"]):
        return ["063"]
    
    # 導入関連
    if contains_any(text, ["いつから", "すぐ", "即日"]):
        return ["060"]
    
    if "設定" in text and contains_any(text, ["難しい", "簡単"]):
        return ["0603"]
    
    return None


# ========================================
# メイン応答判定ロジック
# ========================================

def get_response(
    user_text: str,
    current_phase: str,
    state: Optional[Dict] = None
) -> Tuple[List[str], str, Dict]:
    """
    ユーザーの発話から応答テンプレート、Phase、更新されたStateを返す
    
    Args:
        user_text: ユーザーの発話テキスト
        current_phase: 現在のPhase
        state: 現在のState（オプション）
    
    Returns:
        (template_ids, new_phase, updated_state)
    """
    if state is None:
        state = {}
    
    logger.info(f"dialogue_flow.get_response: text='{user_text}', phase={current_phase}")
    
    # ステップ0: 無音検知
    if is_silence(user_text):
        silence_count = state.get("silence_count", 0) + 1
        if silence_count == 1:
            # 1回目: 催促
            logger.warning("無音検知（1回目）→ 催促")
            return (["110"], current_phase, {"silence_count": 1})
        else:
            # 2回目: ハンドオフ
            logger.warning("無音検知（2回目）→ ハンドオフ")
            return (["0604"], "HANDOFF_CONFIRM_WAIT", {})
    
    # ステップ1: 最優先（Phaseに関係なく処理）
    if is_handoff_request(user_text):
        logger.info("ハンドオフ要求検出")
        return (["0604"], "HANDOFF_CONFIRM_WAIT", {})
    
    if is_end_call(user_text):
        logger.info("通話終了検出")
        return (["086"], "END", {})
    
    if is_not_heard(user_text):
        logger.info("聞き取れない発話検出")
        return (["0602"], current_phase, state)
    
    # ステップ2: 明確な質問の判定（即答）- Phase無視して処理
    response = check_clear_questions(user_text)
    if response:
        logger.info(f"明確な質問検出 → {response}")
        return (response, "QA", {})
    
    # ステップ3: Phase別の処理
    if current_phase == "WAITING_PRICE_TYPE":
        logger.info("WAITING_PRICE_TYPE Phase: ユーザー回答を処理")
        return handle_price_type_response(user_text, state)
    
    if current_phase == "WAITING_FUNCTION_TYPE":
        logger.info("WAITING_FUNCTION_TYPE Phase: ユーザー回答を処理")
        return handle_function_type_response(user_text, state)
    
    # TODO: 将来追加
    # if current_phase == "WAITING_SETUP_TYPE":
    #     return handle_setup_type_response(user_text, state)
    
    # ステップ4: 曖昧な質問の判定（聞き返し）
    if is_ambiguous_price_question(user_text):
        logger.info("曖昧な料金質問検出 → 聞き返し")
        return (["115"], "WAITING_PRICE_TYPE", {"waiting_retry_count": 0})
    
    if is_ambiguous_function_question(user_text):
        logger.info("曖昧な機能質問検出 → 聞き返し")
        return (["117"], "WAITING_FUNCTION_TYPE", {"waiting_retry_count": 0})
    
    # TODO: 将来追加
    # if is_ambiguous_setup_question(user_text):
    #     return (["120"], "WAITING_SETUP_TYPE", {"waiting_retry_count": 0})
    
    # ステップ5: どれにも該当しない場合
    logger.warning(f"どのパターンにも該当せず → UNKNOWN: {user_text}")
    return (["114"], "QA", {})

