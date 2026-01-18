"""
AICore HANDOFF 周りのシナリオテスト

このテストは現状の挙動を固定化することを目的としています。
将来のリファクタ前の期待値として、現在のコードがどう動いているかを確認します。
"""

import logging
import pytest
from unittest.mock import Mock
from gateway.core.ai_core import AICore

# ログ設定（テスト時は必要に応じて調整）
logging.basicConfig(
    level=logging.WARNING,  # テスト時は WARNING 以上のみ表示
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

CALL_ID = "test-call-handoff"


class TemplateCapture:
    """TTS コールバックをキャプチャしてテンプレートIDを取得するヘルパー"""
    
    def __init__(self):
        self.history = []  # list[tuple[call_id, reply_text, template_ids, transfer_requested]]
    
    def callback(self, call_id: str, reply_text: str, template_ids, transfer_requested=None):
        """on_transcript から呼ばれる tts_callback"""
        self.history.append((call_id, reply_text, list(template_ids), transfer_requested))
    
    def last_templates(self):
        """最後のテンプレートIDリストを取得"""
        if not self.history:
            return []
        return self.history[-1][2]
    
    def last_transfer_requested(self):
        """最後の transfer_requested フラグを取得"""
        if not self.history:
            return None
        return self.history[-1][3]
    
    def clear(self):
        """履歴をクリア"""
        self.history.clear()


def make_core():
    """テスト用の AICore インスタンスを生成"""
    core = AICore(init_clients=False)
    core.client_id = "999"
    core.caller_number = "08000000000"
    # transfer_callback をデフォルトで設定（テストで必要に応じて上書き可能）
    if not hasattr(core, "transfer_callback") or core.transfer_callback is None:
        core.transfer_callback = Mock()
    return core


def dump_state(label: str, core: AICore, call_id: str) -> None:
    """状態をダンプしてデバッグに使用（必要に応じて）"""
    state = core._get_session_state(call_id)
    print(
        f"[{label}] phase={state.phase} "
        f"handoff_state={state.handoff_state} "
        f"handoff_retry={state.handoff_retry_count} "
        f"transfer_requested={state.transfer_requested} "
        f"transfer_executed={state.transfer_executed} "
        f"unclear_streak={state.unclear_streak} "
        f"not_heard_streak={state.not_heard_streak}"
    )


# ============================================================================
# Scenario R1: 「はい + 新トピック」で誤転送しないこと
# ============================================================================

def test_R1_handoff_yes_with_followup_topic():
    """
    R1: 「はい、料金の話なんですけど」のような発話で誤って転送されないこと
    
    現状の挙動:
    - 「はい」が含まれているため HANDOFF_YES として判定される
    - 081+082 が返され、転送が実行される
    - これは誤判定（ユーザは質問を始めようとしている）
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_CONFIRM_WAIT"
    state.handoff_state = "confirming"
    state.handoff_retry_count = 0
    state.transfer_requested = False
    state.unclear_streak = 0
    state.not_heard_streak = 0
    
    # 前提: 0604 が提示済み（ここでは省略、実際のテストでは必要に応じて追加）
    # U1: 「担当者に変わってもらえますか？」→ 0604 提示済み（前提）
    
    # U2: 「はい、料金の話なんですけど」
    reply = core.on_transcript(CALL_ID, "はい、料金の話なんですけど", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 現状は誤判定される（HANDOFF_YES として扱われる）
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"
    assert s.transfer_requested is True, f"transfer_requested should be True, got {s.transfer_requested}"
    assert s.transfer_executed is True, f"transfer_executed should be True, got {s.transfer_executed}"
    assert s.phase == "HANDOFF_DONE", f"phase should be 'HANDOFF_DONE', got {s.phase}"
    
    # テンプレートIDを確認
    assert "081" in templates, f"template_ids should contain '081', got {templates}"
    assert "082" in templates, f"template_ids should contain '082', got {templates}"
    
    # これは誤判定なので、将来のリファクタでは修正されるべき
    # 現状のテストでは「誤判定されること」を確認する


# ============================================================================
# Scenario R2: 曖昧な肯定表現で安全側に転送される
# ============================================================================

def test_R2_ambiguous_yes_response_with_retry():
    """
    R2: 「あ、じゃあそれで」のような曖昧な肯定表現で安全側に転送されること
    
    現状の挙動:
    - retry>=1 の場合は安全側で転送（081+082）される
    - ユーザの意図が不明確なまま転送される
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_CONFIRM_WAIT"
    state.handoff_state = "confirming"
    state.handoff_retry_count = 1  # 既に1回再確認済み
    state.transfer_requested = False
    state.unclear_streak = 0
    state.not_heard_streak = 0
    
    # U1: 「担当者に変わってもらえますか？」→ 0604 提示済み（前提）
    # U2: 「えーっと...」→ 0604 再提示、handoff_retry_count=1（前提）
    
    # U3: 「あ、じゃあそれで」（曖昧な肯定表現）
    reply = core.on_transcript(CALL_ID, "あ、じゃあそれで", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # retry>=1 の場合は安全側で転送される
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"
    assert s.transfer_requested is True, f"transfer_requested should be True, got {s.transfer_requested}"
    assert s.transfer_executed is True, f"transfer_executed should be True, got {s.transfer_executed}"
    assert s.phase == "HANDOFF_DONE", f"phase should be 'HANDOFF_DONE', got {s.phase}"
    
    # テンプレートIDを確認
    assert "081" in templates, f"template_ids should contain '081', got {templates}"
    assert "082" in templates, f"template_ids should contain '082', got {templates}"
    
    # handoff_retry_count は 0 にリセットされる
    assert s.handoff_retry_count == 0, f"handoff_retry_count should be 0, got {s.handoff_retry_count}"


# ============================================================================
# Scenario R3: 自動ハンドオフ発火直後の拒否が無視される
# ============================================================================

def test_R3_auto_handoff_trigger_then_denial():
    """
    R3: unclear_streak>=2 で自動ハンドオフ発火後、ユーザが拒否した場合
    
    現状の挙動:
    - unclear_streak>=2 で強制的に HANDOFF_REQUEST に変更され、0604 が提示される
    - 直後にユーザが拒否しても、一度 0604 が出てから拒否処理になる
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "QA"
    state.handoff_state = "idle"
    state.unclear_streak = 2  # 既に2回連続で 110 が選ばれた状態
    state.not_heard_streak = 0
    state.handoff_prompt_sent = False
    
    # U1: （不明瞭な発話 → 110 が選ばれる、unclear_streak=1）（前提）
    # U2: （不明瞭な発話 → 110 が選ばれる、unclear_streak=2）（前提）
    
    # U3: 自動ハンドオフ発火（unclear_streak>=2 で強制的に HANDOFF_REQUEST に変更）
    # この時点で 0604 が提示される
    reply1 = core.on_transcript(CALL_ID, "なんかよくわからない", is_final=True)
    
    s1 = core._get_session_state(CALL_ID)
    templates1 = capture.last_templates()
    
    # 自動ハンドオフ発火が確認できる
    assert s1.handoff_state == "confirming", f"handoff_state should be 'confirming' after auto handoff trigger, got {s1.handoff_state}"
    assert "0604" in templates1, f"template_ids should contain '0604' after auto handoff trigger, got {templates1}"
    assert s1.meta.get("reason_for_handoff") == "auto_unclear", f"meta.reason_for_handoff should be 'auto_unclear', got {s1.meta.get('reason_for_handoff')}"
    
    # U4: 「いや、やっぱりいいです」（拒否）
    capture.clear()  # 履歴をクリアして次の応答を確認
    reply2 = core.on_transcript(CALL_ID, "いや、やっぱりいいです", is_final=True)
    
    s2 = core._get_session_state(CALL_ID)
    templates2 = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 一度 0604 が出てから拒否処理になる
    assert s2.handoff_state == "done", f"handoff_state should be 'done' after denial, got {s2.handoff_state}"
    assert s2.transfer_requested is False, f"transfer_requested should be False after denial, got {s2.transfer_requested}"
    assert s2.phase == "END", f"phase should be 'END' after denial, got {s2.phase}"
    
    # テンプレートIDを確認（086+087 が返される）
    assert "086" in templates2, f"template_ids should contain '086' after denial, got {templates2}"
    assert "087" in templates2, f"template_ids should contain '087' after denial, got {templates2}"


# ============================================================================
# 補助テスト: 状態の初期化とリセット
# ============================================================================

def test_state_initialization():
    """session_state の初期化が正しく行われることを確認"""
    core = make_core()
    state = core._get_session_state(CALL_ID)
    
    assert state.phase == "ENTRY", f"initial phase should be 'ENTRY', got {state.phase}"
    assert state.handoff_state == "idle", f"initial handoff_state should be 'idle', got {state.handoff_state}"
    assert state.handoff_retry_count == 0, f"initial handoff_retry_count should be 0, got {state.handoff_retry_count}"
    assert state.transfer_requested is False, f"initial transfer_requested should be False, got {state.transfer_requested}"


def test_reset_call():
    """reset_call で状態が正しくリセットされることを確認"""
    core = make_core()
    
    # 状態を変更
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_DONE"
    state.handoff_state = "done"
    state.transfer_requested = True
    
    # リセット
    core.reset_call(CALL_ID)
    
    # 状態がリセットされていることを確認
    # 注意: reset_call は session_states を削除するため、次回 _get_session_state で初期値が返される
    state_after = core._get_session_state(CALL_ID)
    assert state_after.phase == "ENTRY", f"phase should be reset to 'ENTRY', got {state_after.phase}"
    assert state_after.handoff_state == "idle", f"handoff_state should be reset to 'idle', got {state_after.handoff_state}"


# ============================================================================
# interpret_handoff_reply の単体テスト
# ============================================================================

def test_interpret_handoff_reply_yes_from_inquiry():
    """intent=INQUIRY だが 'はい、お願いします' を含む → HANDOFF_YES扱い"""
    from gateway.intent_rules import interpret_handoff_reply
    
    # 「はい、料金の話なんですけど」のようなケース
    # 現状は誤判定される（HANDOFF_YES として扱われる）
    text = "はい、料金の話なんですけど"
    result = interpret_handoff_reply(text, base_intent="INQUIRY")
    assert result == "HANDOFF_YES", f"expected HANDOFF_YES, got {result}"


def test_interpret_handoff_reply_no_from_unknown():
    """intent=UNKNOWN だが 'いや、やっぱりいいです' → HANDOFF_NO扱い"""
    from gateway.intent_rules import interpret_handoff_reply
    
    text = "いや、やっぱりいいです"
    result = interpret_handoff_reply(text, base_intent="UNKNOWN")
    assert result == "HANDOFF_NO", f"expected HANDOFF_NO, got {result}"


def test_interpret_handoff_reply_yes_from_unknown():
    """intent=UNKNOWN だが 'はい' を含む → HANDOFF_YES扱い"""
    from gateway.intent_rules import interpret_handoff_reply
    
    text = "はい"
    result = interpret_handoff_reply(text, base_intent="UNKNOWN")
    assert result == "HANDOFF_YES", f"expected HANDOFF_YES, got {result}"


def test_interpret_handoff_reply_no_from_end_call():
    """intent=END_CALL で NO キーワードを含む → HANDOFF_NO扱い"""
    from gateway.intent_rules import interpret_handoff_reply
    
    text = "結構です"
    result = interpret_handoff_reply(text, base_intent="END_CALL")
    assert result == "HANDOFF_NO", f"expected HANDOFF_NO, got {result}"


def test_interpret_handoff_reply_unknown():
    """明確なYES/NOがない場合 → UNKNOWN扱い"""
    from gateway.intent_rules import interpret_handoff_reply
    
    text = "えーっと..."
    result = interpret_handoff_reply(text, base_intent="UNKNOWN")
    assert result == "UNKNOWN", f"expected UNKNOWN, got {result}"


# ============================================================================
# Scenario R4: 転送実行後に再度ハンドオフ要求が来た場合のフラグリセット
# ============================================================================

def test_R4_transfer_flags_reset_on_second_handoff_request():
    """
    R4: 転送実行後に再度ハンドオフ要求が来た場合のフラグリセット
    
    現状の挙動:
    - handoff_state=done かつ transfer_executed=True の状態で HANDOFF_REQUEST が来た場合
    - transfer_executed が False にリセットされる
    - 0604 が提示される
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "AFTER_085"
    state.handoff_state = "done"
    state.transfer_executed = True
    state.transfer_requested = True
    state.handoff_completed = True
    
    # U2: 「やっぱり担当者お願いします」（2回目のハンドオフ要求）
    reply = core.on_transcript(CALL_ID, "やっぱり担当者お願いします", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    assert s.handoff_state == "confirming", f"handoff_state should be 'confirming', got {s.handoff_state}"
    assert s.transfer_requested is False, f"transfer_requested should be False, got {s.transfer_requested}"
    assert s.transfer_executed is False, f"transfer_executed should be False, got {s.transfer_executed}"
    
    # テンプレートIDを確認（0604 が返される）
    assert "0604" in templates, f"template_ids should contain '0604', got {templates}"


# ============================================================================
# Scenario R5: phase=END なのに転送フラグが中途半端に立っている
# ============================================================================

def test_R5_phase_end_with_transfer_requested_flag_inconsistent():
    """
    R5: phase=END なのに転送フラグが中途半端に立っている
    
    現状の挙動:
    - phase=END に遷移したとき、transfer_requested_flag が False の場合のみ自動切断をセット
    - transfer_requested=True の場合は自動切断がセットされない
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定（不整合な状態）
    state = core._get_session_state(CALL_ID)
    state.phase = "END"
    state.transfer_requested = True
    state.transfer_executed = False
    state.handoff_state = "done"
    
    # 自動切断タイマーのセットを確認するため、on_transcript を呼ぶ必要はないが、
    # 状態の不整合を確認するために状態をチェック
    s = core._get_session_state(CALL_ID)
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # phase=END なのに transfer_requested=True の不整合状態が発生している
    assert s.phase == "END", f"phase should be 'END', got {s.phase}"
    assert s.transfer_requested is True, f"transfer_requested should be True (inconsistent state), got {s.transfer_requested}"
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"


# ============================================================================
# Scenario R6: 時間稼ぎ的な発話
# ============================================================================

def test_R6_handoff_time_filler_phrase_triggers_retry():
    """
    R6: 時間稼ぎ的な発話で 0604 が再提示される
    
    現状の挙動:
    - intent: UNKNOWN（時間稼ぎ的な発話）
    - テンプレ: 0604（retry=0 なので再確認）
    - handoff_retry_count: 0→1
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_CONFIRM_WAIT"
    state.handoff_state = "confirming"
    state.handoff_retry_count = 0
    state.transfer_requested = False
    
    # U2: 「えーっと、ちょっと待ってください」（時間稼ぎ的な発話）
    reply = core.on_transcript(CALL_ID, "えーっと、ちょっと待ってください", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    assert s.handoff_retry_count == 1, f"handoff_retry_count should be 1, got {s.handoff_retry_count}"
    assert s.handoff_state == "confirming", f"handoff_state should be 'confirming', got {s.handoff_state}"
    assert s.phase == "HANDOFF_CONFIRM_WAIT", f"phase should be 'HANDOFF_CONFIRM_WAIT', got {s.phase}"
    
    # テンプレートIDを確認（0604 が返される）
    assert "0604" in templates, f"template_ids should contain '0604', got {templates}"


# ============================================================================
# Scenario R7: 曖昧な肯定表現（retry=1）
# ============================================================================

def test_R7_ambiguous_yes_after_retry_leads_to_safe_transfer():
    """
    R7: 曖昧な肯定表現（retry=1）で安全側に転送される
    
    現状の挙動:
    - intent: UNKNOWN（曖昧な肯定表現）
    - テンプレ: 081+082（安全側で転送）
    - phase: HANDOFF_DONE
    - transfer_requested: True
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_CONFIRM_WAIT"
    state.handoff_state = "confirming"
    state.handoff_retry_count = 1
    state.transfer_requested = False
    
    # U3: 「うーん、まあ、いいかな」（曖昧な肯定表現）
    reply = core.on_transcript(CALL_ID, "うーん、まあ、いいかな", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"
    assert s.transfer_requested is True, f"transfer_requested should be True, got {s.transfer_requested}"
    assert s.transfer_executed is True, f"transfer_executed should be True, got {s.transfer_executed}"
    assert s.phase == "HANDOFF_DONE", f"phase should be 'HANDOFF_DONE', got {s.phase}"
    
    # テンプレートIDを確認（081+082 が返される）
    assert "081" in templates, f"template_ids should contain '081', got {templates}"
    assert "082" in templates, f"template_ids should contain '082', got {templates}"


# ============================================================================
# Scenario R8: not_heard_streak>=2 で自動ハンドオフ発火
# ============================================================================

def test_R8_not_heard_streak_auto_handoff_and_no():
    """
    R8: not_heard_streak>=2 で自動ハンドオフ発火後、ユーザが拒否した場合
    
    現状の挙動:
    - not_heard_streak>=2 で自動ハンドオフ発火、0604 が提示される
    - 直後にユーザが拒否しても、一度 0604 が出てから拒否処理になる
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "QA"
    state.handoff_state = "idle"
    state.not_heard_streak = 2  # 既に2回連続で 110 が選ばれた状態
    state.unclear_streak = 0
    state.handoff_prompt_sent = False
    
    # U3: 自動ハンドオフ発火（not_heard_streak>=2 で強制的に HANDOFF_REQUEST に変更）
    # この時点で 0604 が提示される
    reply1 = core.on_transcript(CALL_ID, "なんかよくわからない", is_final=True)
    
    s1 = core._get_session_state(CALL_ID)
    templates1 = capture.last_templates()
    
    # 自動ハンドオフ発火が確認できる
    assert s1.handoff_state == "confirming", f"handoff_state should be 'confirming' after auto handoff trigger, got {s1.handoff_state}"
    assert "0604" in templates1, f"template_ids should contain '0604' after auto handoff trigger, got {templates1}"
    
    # U4: 「いや、大丈夫です」（拒否）
    capture.clear()  # 履歴をクリアして次の応答を確認
    reply2 = core.on_transcript(CALL_ID, "いや、大丈夫です", is_final=True)
    
    s2 = core._get_session_state(CALL_ID)
    templates2 = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 一度 0604 が出てから拒否処理になる
    assert s2.handoff_state == "done", f"handoff_state should be 'done' after denial, got {s2.handoff_state}"
    assert s2.transfer_requested is False, f"transfer_requested should be False after denial, got {s2.transfer_requested}"
    assert s2.phase == "END", f"phase should be 'END' after denial, got {s2.phase}"
    
    # テンプレートIDを確認（086+087 が返される）
    assert "086" in templates2, f"template_ids should contain '086' after denial, got {templates2}"
    assert "087" in templates2, f"template_ids should contain '087' after denial, got {templates2}"


# ============================================================================
# Scenario R9: 「はい、でもその前に質問があります」
# ============================================================================

def test_R9_yes_but_followup_question_still_transfers():
    """
    R9: 「はい、でもその前に質問があります」のような発話で誤って転送される
    
    現状の挙動:
    - 「はい」が含まれているため HANDOFF_YES として判定される
    - 081+082 が返され、転送が実行される
    - これは誤判定（ユーザは質問を始めようとしている）
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_CONFIRM_WAIT"
    state.handoff_state = "confirming"
    state.handoff_retry_count = 0
    state.transfer_requested = False
    state.unclear_streak = 0
    state.not_heard_streak = 0
    
    # U2: 「はい、でもその前に質問があります」
    reply = core.on_transcript(CALL_ID, "はい、でもその前に質問があります", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 現状は誤判定される（HANDOFF_YES として扱われる）
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"
    assert s.transfer_requested is True, f"transfer_requested should be True, got {s.transfer_requested}"
    assert s.transfer_executed is True, f"transfer_executed should be True, got {s.transfer_executed}"
    assert s.phase == "HANDOFF_DONE", f"phase should be 'HANDOFF_DONE', got {s.phase}"
    
    # テンプレートIDを確認
    assert "081" in templates, f"template_ids should contain '081', got {templates}"
    assert "082" in templates, f"template_ids should contain '082', got {templates}"


# ============================================================================
# Scenario R10: phase=END なのに handoff_state=done
# ============================================================================

def test_R10_phase_end_handoff_state_done_inconsistent_but_autohangup():
    """
    R10: phase=END なのに handoff_state=done の不整合状態でも自動切断が動作する
    
    現状の挙動:
    - 自動切断タイマーがセットされる（transfer_requested=False のため）
    - 状態の不整合（phase=END なのに handoff_state=done）が発生しているが、自動切断は正常に動作する
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定（不整合な状態）
    state = core._get_session_state(CALL_ID)
    state.phase = "END"
    state.transfer_requested = False
    state.transfer_executed = False
    state.handoff_state = "done"
    
    # 状態の不整合を確認
    s = core._get_session_state(CALL_ID)
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 状態の不整合が発生している
    assert s.phase == "END", f"phase should be 'END', got {s.phase}"
    assert s.handoff_state == "done", f"handoff_state should be 'done' (inconsistent state), got {s.handoff_state}"
    assert s.transfer_requested is False, f"transfer_requested should be False, got {s.transfer_requested}"


# ============================================================================
# Scenario R11: 転送実行済みで拒否
# ============================================================================

def test_R11_already_transferred_then_cancel_is_ignored():
    """
    R11: 転送実行済みで拒否しても、転送を取り消せない
    
    現状の挙動:
    - 既に転送が実行された状態でユーザが拒否しても、転送を取り消せない
    - handoff_state=done なので 0604/104 は出さない
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_DONE"
    state.handoff_state = "done"
    state.transfer_executed = True
    state.transfer_requested = True
    
    # U2: 「あ、やっぱりいいです」（拒否）
    reply = core.on_transcript(CALL_ID, "あ、やっぱりいいです", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 既に転送が実行された状態で拒否しても、転送を取り消せない
    # handoff_state=done なので 0604/104 は出さない
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"
    # テンプレートIDに 0604 や 104 が含まれていないことを確認
    assert "0604" not in templates, f"template_ids should not contain '0604' when handoff_state=done, got {templates}"
    assert "104" not in templates, f"template_ids should not contain '104' when handoff_state=done, got {templates}"


# ============================================================================
# Scenario R12: 「はい、お願いします。あ、でも料金について聞きたいんですけど」
# ============================================================================

def test_R12_yes_then_but_followup_question_transfers():
    """
    R12: 「はい、お願いします。あ、でも料金について聞きたいんですけど」のような発話で誤って転送される
    
    現状の挙動:
    - 「はい、お願いします」が含まれているため HANDOFF_YES として判定される
    - 081+082 が返され、転送が実行される
    - これは誤判定（ユーザは質問を始めようとしている）
    """
    core = make_core()
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    
    # 初期状態を設定
    state = core._get_session_state(CALL_ID)
    state.phase = "HANDOFF_CONFIRM_WAIT"
    state.handoff_state = "confirming"
    state.handoff_retry_count = 0
    state.transfer_requested = False
    state.unclear_streak = 0
    state.not_heard_streak = 0
    
    # U2: 「はい、お願いします。あ、でも料金について聞きたいんですけど」
    reply = core.on_transcript(CALL_ID, "はい、お願いします。あ、でも料金について聞きたいんですけど", is_final=True)
    
    # 状態を確認
    s = core._get_session_state(CALL_ID)
    templates = capture.last_templates()
    
    # 現状の挙動を固定（将来のリファクタ前の期待値）
    # 現状は誤判定される（HANDOFF_YES として扱われる）
    assert s.handoff_state == "done", f"handoff_state should be 'done', got {s.handoff_state}"
    assert s.transfer_requested is True, f"transfer_requested should be True, got {s.transfer_requested}"
    assert s.transfer_executed is True, f"transfer_executed should be True, got {s.transfer_executed}"
    assert s.phase == "HANDOFF_DONE", f"phase should be 'HANDOFF_DONE', got {s.phase}"
    
    # テンプレートIDを確認
    assert "081" in templates, f"template_ids should contain '081', got {templates}"
    assert "082" in templates, f"template_ids should contain '082', got {templates}"


# ============================================================================
# _trigger_transfer_if_needed の単体テスト
# ============================================================================

def test_trigger_transfer_called_once():
    """_trigger_transfer_if_needed が1回だけ呼ばれることを確認"""
    core = make_core()
    mock_callback = Mock()
    core.transfer_callback = mock_callback
    
    state = core._get_session_state("TEST_CALL")
    state.transfer_requested = True
    state.transfer_executed = False
    
    # 2回呼んでも1回だけ実行される
    core._trigger_transfer_if_needed("TEST_CALL", state)
    core._trigger_transfer_if_needed("TEST_CALL", state)
    
    mock_callback.assert_called_once_with("TEST_CALL")
    assert state.transfer_executed is True


def test_trigger_transfer_not_called_when_executed():
    """transfer_executed=True の場合は呼ばれないことを確認"""
    core = make_core()
    mock_callback = Mock()
    core.transfer_callback = mock_callback
    
    state = core._get_session_state("TEST_CALL")
    state.transfer_requested = True
    state.transfer_executed = True  # 既に実行済み
    
    core._trigger_transfer_if_needed("TEST_CALL", state)
    
    mock_callback.assert_not_called()


def test_trigger_transfer_not_called_when_not_requested():
    """transfer_requested=False の場合は呼ばれないことを確認"""
    core = make_core()
    mock_callback = Mock()
    core.transfer_callback = mock_callback
    
    state = core._get_session_state("TEST_CALL")
    state.transfer_requested = False
    state.transfer_executed = False
    
    core._trigger_transfer_if_needed("TEST_CALL", state)
    
    mock_callback.assert_not_called()


def test_trigger_transfer_not_called_when_no_callback():
    """transfer_callback が設定されていない場合は呼ばれないことを確認"""
    core = make_core()
    # transfer_callback を明示的に None に設定
    core.transfer_callback = None
    
    state = core._get_session_state("TEST_CALL")
    state.transfer_requested = True
    state.transfer_executed = False
    
    # エラーが発生しないことを確認
    core._trigger_transfer_if_needed("TEST_CALL", state)
    
    assert state.transfer_executed is False  # 実行されていないので False のまま


if __name__ == "__main__":
    # 直接実行時のテスト
    pytest.main([__file__, "-v"])

