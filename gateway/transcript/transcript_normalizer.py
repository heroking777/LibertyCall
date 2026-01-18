"""
Whisper出力のテキスト正規化モジュール

電話音声の「もしもし」を誤認識した場合に補正する。
"""
import re
import logging
from typing import Tuple, Optional, List

logger = logging.getLogger(__name__)

# 「もしもし」に補正すべきパターンリスト（将来的に追加しやすい構造）
HELLO_CORRECTION_PATTERNS: List[str] = [
    # ます系
    "ます", "ます。", "ます、", "ますー", "まっす", "ます.", "ます,",
    "ますます", "ますます。", "ますます、",
    # ロッド系
    "ロッドロッド", "ロッド", "ロッド。", "ロッド、",
    # マス系
    "マス", "マス。", "マス、",
    # 短い単発文字
    "ま", "ま。", "ま、", "ま.", "ま,",
    "あ", "あ。", "あ、", "あ.", "あ,",
    "え", "え。", "え、", "え.", "え,",
    "お", "お。", "お、", "お.", "お,",
    "い", "い。", "い、", "い.", "い,",
    "う", "う。", "う、", "う.", "う,",
    "まっ", "まっ。", "まっ、",
]


def normalize_transcript(
    call_id: str,
    text: str,
    turn_index: int,
    elapsed_from_call_start_ms: int = 0
) -> Tuple[str, Optional[str]]:
    """
    Whisper出力テキストを正規化する。
    
    :param call_id: 通話ID
    :param text: Whisperの生出力テキスト
    :param turn_index: この通話で何ターン目のユーザー発話か（1始まり）
    :param elapsed_from_call_start_ms: 通話開始からの経過時間（ミリ秒）
    :return: (normalized_text, rule_applied) タプル
              rule_applied: 適用されたルール名（None=補正なし）
    """
    if not text:
        return text, None
    
    # デフォルト：補正なし
    normalized_text = text
    rule_applied = None
    
    # 条件1: turn_index == 1（最初のユーザー発話のみ）
    if turn_index == 1:
        # テキストを整形（全角・半角・句読点の正規化）
        text_normalized = _normalize_text_format(text)
        
        # 条件2: 文字数が1〜6文字程度
        if 1 <= len(text_normalized) <= 6:
            # 条件3: ひらがな・カタカナだけ（英数字・漢字がない）
            if _is_hiragana_katakana_only(text_normalized):
                # 条件4: パターンリストに一致するか、意味のない短い文字列
                if _should_correct_to_hello(text_normalized):
                    normalized_text = "もしもし"
                    rule_applied = "HELLO_NORMALIZATION"
                    return normalized_text, rule_applied
    
    return normalized_text, rule_applied


def _normalize_text_format(text: str) -> str:
    """
    テキストを整形（全角・半角・句読点の正規化）。
    
    :param text: 元のテキスト
    :return: 整形後のテキスト
    """
    if not text:
        return text
    
    # 全角・半角の句読点を統一
    text = text.replace("。", "。").replace(".", "。")
    text = text.replace("、", "、").replace(",", "、")
    text = text.replace("ー", "ー").replace("-", "ー")
    
    # 前後の空白を削除
    return text.strip()


def _is_hiragana_katakana_only(text: str) -> bool:
    """
    ひらがな・カタカナのみかどうかを判定（英数字・漢字がない）。
    
    :param text: 判定対象テキスト
    :return: ひらがな・カタカナのみの場合True
    """
    if not text:
        return False
    
    # ひらがな・カタカナ・句読点のみのパターン
    # 英数字・漢字が含まれていないかチェック
    pattern = r'^[ぁ-ゖァ-ヶー。、.、\s]+$'
    return bool(re.match(pattern, text))


def _should_correct_to_hello(text: str) -> bool:
    """
    「もしもし」に補正すべきかどうかを判定。
    
    :param text: 判定対象テキスト
    :return: 補正すべき場合True
    """
    if not text:
        return False
    
    text_stripped = text.strip()
    
    # パターン1: パターンリストに一致
    if text_stripped in HELLO_CORRECTION_PATTERNS:
        return True
    
    # パターン2: 意味のない短い文字列（1-3文字のひらがな・カタカナのみ）
    if _is_meaningless_short_text(text_stripped):
        return True
    
    return False


def _is_meaningless_short_text(text: str) -> bool:
    """
    意味のない短い文字列かどうかを判定。
    
    :param text: 判定対象テキスト
    :return: 意味のない短い文字列の場合True
    """
    if not text:
        return False
    
    # "もし"や"も"が含まれている場合は補正しない（既に「もしもし」っぽい）
    if "もし" in text or "も" in text:
        return False
    
    # 句読点を除いた文字数が1-3文字で、ひらがな・カタカナのみ
    text_no_punct = re.sub(r'[。、.、\s]', '', text)
    if 1 <= len(text_no_punct) <= 3:
        # ひらがな・カタカナのみかチェック
        if re.match(r'^[ぁ-ゖァ-ヶー]+$', text_no_punct):
            return True
    
    return False

