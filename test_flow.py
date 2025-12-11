import logging
from libertycall.gateway.ai_core import AICore
from libertycall.gateway import ai_core as ai_module
from libertycall.gateway import intent_rules as intent_module
def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
# ==== テスト用パッチ ====
def patch_intent_rules():
    """
    テスト用に classify_intent を上書きして、
    日本語の「担当者」「はい」「結構です」で
    確実に HANDOFF_* が返るようにする。
    """
    original_ai = ai_module.classify_intent
    original_ir = intent_module.classify_intent
    def fake_classify_intent(text: str):
        t = (text or "").strip()
        # 担当者につないでほしい → HANDOFF_REQUEST
        if t in ("担当者", "担当者？", "担当者に繋いで", "担当者につないで", "担当者お願いします"):
            return "HANDOFF_REQUEST"
        # 転送 OK 系 → HANDOFF_YES
        if t in ("はい", "はいはい", "お願いします", "繋いでください", "つないでください"):
            return "HANDOFF_YES"
        # 転送 NO 系 → HANDOFF_NO
        if t in ("いいえ", "結構です", "けっこうです", "大丈夫です"):
            return "HANDOFF_NO"
        # それ以外は元のロジックに任せる（なければ UNKNOWN）
        if original_ir is not None:
            result = original_ir(t)
            return result or "UNKNOWN"
        return "UNKNOWN"
    # モジュール側と ai_core 側の両方を差し替え
    ai_module.classify_intent = fake_classify_intent
    intent_module.classify_intent = fake_classify_intent
    return original_ai, original_ir
def restore_intent_rules(original_ai, original_ir) -> None:
    ai_module.classify_intent = original_ai
    intent_module.classify_intent = original_ir
def patch_call_log():
    """
    テスト中は _append_call_log を無効化して、
    client_id=None でのパス結合エラーを避ける。
    """
    original = ai_module.AICore._append_call_log
    def fake_append(self, role: str, text: str, template_id=None) -> None:
        # ログは何もしない（会話ロジックに影響しない）
        return None
    ai_module.AICore._append_call_log = fake_append
    return original
def restore_call_log(original) -> None:
    ai_module.AICore._append_call_log = original
# ==== テンプレ取得用ヘルパ ====
class TemplateCapture:
    def __init__(self) -> None:
        self.history = []  # list[tuple[call_id, reply_text, template_ids]]
    def callback(self, call_id: str, reply_text: str, template_ids, transfer_requested=None):
        # on_transcript から呼ばれる tts_callback
        # transfer_requested はオプショナル（既存テストとの互換性のため）
        self.history.append((call_id, reply_text, list(template_ids)))
    def last_templates(self):
        if not self.history:
            return []
        return self.history[-1][2]
# ==== テストケース ====
def dump_state(label: str, core: AICore, call_id: str) -> None:
    state = core._get_session_state(call_id)
    print(
        f"[{label}] phase={state.get('phase')}"
        f" last_intent={state.get('last_intent')}"
        f" handoff_state={state.get('handoff_state')}"
        f" handoff_retry={state.get('handoff_retry_count')}"
        f" transfer_requested={state.get('transfer_requested')}"
    )
def run_case_yes() -> None:
    """
    シナリオ1:
      USER: 担当者
      USER: はい
    期待:
      1ターン目 → 0604 のみ（104 は含まない）
      2ターン目 → 081 + 082
      handoff_state = done / transfer_requested = True
    """
    core = AICore(init_clients=False)
    call_id = "TEST_HANDOFF_YES"
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    print("\n=== CASE: HANDOFF YES ===")
    # 1ターン目: 担当者
    user1 = "担当者"
    print(f"USER: {user1}")
    core.on_transcript(call_id, user1, is_final=True)
    dump_state("TURN1", core, call_id)
    t1 = capture.last_templates()
    print(f"TURN1 templates={t1}")
    assert t1 == ["0604"], f"TURN1 templates should be ['0604'], got {t1}"
    assert "104" not in t1, f"TURN1 must NOT contain 104, got {t1}"
    # 2ターン目: はい
    user2 = "はい"
    print(f"USER: {user2}")
    core.on_transcript(call_id, user2, is_final=True)
    dump_state("TURN2", core, call_id)
    t2 = capture.last_templates()
    print(f"TURN2 templates={t2}")
    assert t2 == ["081", "082"], f"TURN2 templates should be ['081', '082'], got {t2}"
    assert "104" not in t2, f"TURN2 must NOT contain 104, got {t2}"
    state = core._get_session_state(call_id)
    assert state.get("handoff_state") == "done", "handoff_state should be 'done' for YES case"
    assert state.get("transfer_requested") is True, "transfer_requested should be True for YES case"
def run_case_no() -> None:
    """
    シナリオ2:
      USER: 担当者
      USER: 結構です
    期待:
      1ターン目 → 0604 のみ（104 は含まない）
      2ターン目 → 086 + 087
      handoff_state = done / transfer_requested = False
    """
    core = AICore(init_clients=False)
    call_id = "TEST_HANDOFF_NO"
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    print("\n=== CASE: HANDOFF NO ===")
    # 1ターン目: 担当者
    user1 = "担当者"
    print(f"USER: {user1}")
    core.on_transcript(call_id, user1, is_final=True)
    dump_state("TURN1", core, call_id)
    t1 = capture.last_templates()
    print(f"TURN1 templates={t1}")
    assert t1 == ["0604"], f"TURN1 templates should be ['0604'], got {t1}"
    assert "104" not in t1, f"TURN1 must NOT contain 104, got {t1}"
    # 2ターン目: 結構です
    user2 = "結構です"
    print(f"USER: {user2}")
    core.on_transcript(call_id, user2, is_final=True)
    dump_state("TURN2", core, call_id)
    t2 = capture.last_templates()
    print(f"TURN2 templates={t2}")
    assert t2 == ["086", "087"], f"TURN2 templates should be ['086', '087'], got {t2}"
    assert "104" not in t2, f"TURN2 must NOT contain 104, got {t2}"
    state = core._get_session_state(call_id)
    assert state.get("handoff_state") == "done", "handoff_state should be 'done' for NO case"
    assert state.get("transfer_requested") is False, "transfer_requested should be False for NO case"

def patch_intent_rules_for_unclear_test():
    """
    テスト用に classify_intent と select_template_ids を上書きして、
    tpl=110 が選ばれるようにする。
    """
    from libertycall.gateway import intent_rules as intent_module
    original_classify = intent_module.classify_intent
    original_select = intent_module.select_template_ids
    
    def fake_classify_intent(text: str):
        t = (text or "").strip()
        # 特定のキーワードで UNKNOWN を返す（tpl=110 が選ばれるように）
        if t in ("不明な発話", "聞き取れない", "理解不能"):
            return "UNKNOWN"
        # 通常の回答になるキーワード
        if t in ("ホームページ", "システムについて", "導入について"):
            return "INQUIRY"
        # それ以外は元のロジック
        if original_classify is not None:
            return original_classify(t) or "UNKNOWN"
        return "UNKNOWN"
    
    def fake_select_template_ids(intent: str, text: str):
        # UNKNOWN の場合は空リストを返す（フォールバックで 110 が選ばれる）
        if intent == "UNKNOWN":
            return []
        # INQUIRY の場合は通常テンプレートを返す
        if intent == "INQUIRY":
            return ["006"]
        # それ以外は元のロジック
        if original_select is not None:
            return original_select(intent, text)
        return []
    
    intent_module.classify_intent = fake_classify_intent
    intent_module.select_template_ids = fake_select_template_ids
    return original_classify, original_select

def restore_intent_rules_for_unclear_test(original_classify, original_select):
    from libertycall.gateway import intent_rules as intent_module
    intent_module.classify_intent = original_classify
    intent_module.select_template_ids = original_select

def run_case_unclear_streak_force_handoff() -> None:
    """
    ケース1: 110 → 110 → 強制ハンドオフ
    1. 1ターン目で tpl=110 が選ばれる想定の入力を与える
       unclear_streak が 1 になること
    2. 2ターン目でも tpl=110 が選ばれる想定の入力を与える
       強制的に intent が HANDOFF_REQUEST に書き換わること
       tpl=0604 が選ばれること
       meta に reason_for_handoff == "auto_unclear" と unclear_streak_at_trigger == 2 がセットされていること
    """
    core = AICore(init_clients=False)
    call_id = "TEST_UNCLEAR_STREAK_FORCE"
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    print("\n=== CASE: UNCLEAR STREAK FORCE HANDOFF ===")
    
    # handoff_prompt_sent を True に設定して、UNKNOWN 時に 0604 が選ばれないようにする
    state = core._get_session_state(call_id)
    state["handoff_prompt_sent"] = True
    
    orig_classify, orig_select = patch_intent_rules_for_unclear_test()
    try:
        # 1ターン目: 不明な発話 → tpl=110
        user1 = "不明な発話"
        print(f"USER: {user1}")
        core.on_transcript(call_id, user1, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_1 = state.get("unclear_streak", 0)
        print(f"TURN1 unclear_streak={unclear_streak_1}")
        t1 = capture.last_templates()
        print(f"TURN1 templates={t1}")
        assert unclear_streak_1 == 1, f"TURN1 unclear_streak should be 1, got {unclear_streak_1}"
        assert t1 == ["110"], f"TURN1 templates should be ['110'], got {t1}"
        
        # 2ターン目: 再度不明な発話 → 強制ハンドオフ
        user2 = "聞き取れない"
        print(f"USER: {user2}")
        core.on_transcript(call_id, user2, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_2 = state.get("unclear_streak", 0)
        meta = state.get("meta", {})
        print(f"TURN2 unclear_streak={unclear_streak_2}")
        print(f"TURN2 meta={meta}")
        t2 = capture.last_templates()
        print(f"TURN2 templates={t2}")
        assert t2 == ["0604"], f"TURN2 templates should be ['0604'], got {t2}"
        assert meta.get("reason_for_handoff") == "auto_unclear", f"meta.reason_for_handoff should be 'auto_unclear', got {meta.get('reason_for_handoff')}"
        assert meta.get("unclear_streak_at_trigger") == 2, f"meta.unclear_streak_at_trigger should be 2, got {meta.get('unclear_streak_at_trigger')}"
        assert state.get("handoff_state") == "confirming", f"handoff_state should be 'confirming', got {state.get('handoff_state')}"
    finally:
        restore_intent_rules_for_unclear_test(orig_classify, orig_select)

def run_case_unclear_streak_reset() -> None:
    """
    ケース2: 110 → 通常テンプレ → 110
    1. 1ターン目: tpl=110 が選ばれる入力
       unclear_streak == 1
    2. 2ターン目: 通常テンプレ（006, 010 など）になる入力
       unclear_streak == 0 にリセットされること
    3. 3ターン目: 再度 tpl=110 になる入力
       unclear_streak == 1 であり、まだ強制 HANDOFF は発火しないこと
       meta に reason_for_handoff が付与されていないこと
    """
    core = AICore(init_clients=False)
    call_id = "TEST_UNCLEAR_STREAK_RESET"
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    print("\n=== CASE: UNCLEAR STREAK RESET ===")
    
    # handoff_prompt_sent を True に設定して、UNKNOWN 時に 0604 が選ばれないようにする
    state = core._get_session_state(call_id)
    state["handoff_prompt_sent"] = True
    
    orig_classify, orig_select = patch_intent_rules_for_unclear_test()
    try:
        # 1ターン目: 不明な発話 → tpl=110
        user1 = "不明な発話"
        print(f"USER: {user1}")
        core.on_transcript(call_id, user1, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_1 = state.get("unclear_streak", 0)
        print(f"TURN1 unclear_streak={unclear_streak_1}")
        assert unclear_streak_1 == 1, f"TURN1 unclear_streak should be 1, got {unclear_streak_1}"
        
        # 2ターン目: 通常テンプレートになる入力
        user2 = "ホームページ"
        print(f"USER: {user2}")
        core.on_transcript(call_id, user2, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_2 = state.get("unclear_streak", 0)
        print(f"TURN2 unclear_streak={unclear_streak_2}")
        t2 = capture.last_templates()
        print(f"TURN2 templates={t2}")
        assert unclear_streak_2 == 0, f"TURN2 unclear_streak should be 0 (reset), got {unclear_streak_2}"
        assert "110" not in t2, f"TURN2 should not contain 110, got {t2}"
        
        # 3ターン目: 再度不明な発話 → tpl=110
        user3 = "聞き取れない"
        print(f"USER: {user3}")
        core.on_transcript(call_id, user3, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_3 = state.get("unclear_streak", 0)
        meta = state.get("meta", {})
        print(f"TURN3 unclear_streak={unclear_streak_3}")
        print(f"TURN3 meta={meta}")
        t3 = capture.last_templates()
        print(f"TURN3 templates={t3}")
        assert unclear_streak_3 == 1, f"TURN3 unclear_streak should be 1, got {unclear_streak_3}"
        assert t3 == ["110"], f"TURN3 templates should be ['110'], got {t3}"
        assert meta.get("reason_for_handoff") is None, f"meta.reason_for_handoff should be None, got {meta.get('reason_for_handoff')}"
    finally:
        restore_intent_rules_for_unclear_test(orig_classify, orig_select)

def run_case_handoff_done_reset() -> None:
    """
    ケース3: HANDOFF フロー完了後のリセット
    1. unclear_streak >= 2 の状態から強制 HANDOFF が発火し、tpl=0604 を返すケースを再現
    2. その後、HANDOFF_YES / HANDOFF_NO による handoff_state=done 遷移をシミュレート
    3. handoff_state=done 時点で unclear_streak == 0 にリセットされていることを確認
    4. 以降の通常会話で、unclear_streak が前回の値を引きずらないことを確認
    """
    core = AICore(init_clients=False)
    call_id = "TEST_HANDOFF_DONE_RESET"
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    print("\n=== CASE: HANDOFF DONE RESET ===")
    
    # handoff_prompt_sent を True に設定して、UNKNOWN 時に 0604 が選ばれないようにする
    state = core._get_session_state(call_id)
    state["handoff_prompt_sent"] = True
    
    orig_classify, orig_select = patch_intent_rules_for_unclear_test()
    orig_ai, orig_ir = patch_intent_rules()
    try:
        # 1ターン目: 不明な発話 → tpl=110
        user1 = "不明な発話"
        print(f"USER: {user1}")
        core.on_transcript(call_id, user1, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_1 = state.get("unclear_streak", 0)
        print(f"TURN1 unclear_streak={unclear_streak_1}")
        assert unclear_streak_1 == 1, f"TURN1 unclear_streak should be 1, got {unclear_streak_1}"
        
        # 2ターン目: 再度不明な発話 → 強制ハンドオフ
        user2 = "聞き取れない"
        print(f"USER: {user2}")
        core.on_transcript(call_id, user2, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_2 = state.get("unclear_streak", 0)
        print(f"TURN2 unclear_streak={unclear_streak_2}")
        t2 = capture.last_templates()
        print(f"TURN2 templates={t2}")
        assert t2 == ["0604"], f"TURN2 templates should be ['0604'], got {t2}"
        
        # 3ターン目: HANDOFF_YES → handoff_state=done
        user3 = "はい"
        print(f"USER: {user3}")
        core.on_transcript(call_id, user3, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_3 = state.get("unclear_streak", 0)
        handoff_state = state.get("handoff_state")
        print(f"TURN3 unclear_streak={unclear_streak_3} handoff_state={handoff_state}")
        assert unclear_streak_3 == 0, f"TURN3 unclear_streak should be 0 (reset after handoff_done), got {unclear_streak_3}"
        assert handoff_state == "done", f"handoff_state should be 'done', got {handoff_state}"
        
        # 4ターン目: 通常の会話 → unclear_streak が引きずられないことを確認
        user4 = "ホームページ"
        print(f"USER: {user4}")
        core.on_transcript(call_id, user4, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_4 = state.get("unclear_streak", 0)
        print(f"TURN4 unclear_streak={unclear_streak_4}")
        assert unclear_streak_4 == 0, f"TURN4 unclear_streak should be 0, got {unclear_streak_4}"
    finally:
        restore_intent_rules_for_unclear_test(orig_classify, orig_select)
        restore_intent_rules(orig_ai, orig_ir)

def run_case_existing_handoff_non_interference() -> None:
    """
    ケース4: 既存の HANDOFF_REQUEST との非干渉
    1. ユーザーの明示的なハンドオフ依頼や、キーワードベースなど、従来の HANDOFF_REQUEST を発火させるテストケースに対して、
       unclear_streak の値にかかわらず、
       既存の intent 判定・テンプレ選択が維持されること
    2. このルートでは meta.reason_for_handoff が勝手に auto_unclear にならないこと
    """
    core = AICore(init_clients=False)
    call_id = "TEST_EXISTING_HANDOFF"
    capture = TemplateCapture()
    core.tts_callback = capture.callback
    print("\n=== CASE: EXISTING HANDOFF NON-INTERFERENCE ===")
    
    orig_ai, orig_ir = patch_intent_rules()
    orig_classify, orig_select = patch_intent_rules_for_unclear_test()
    try:
        # まず unclear_streak を 1 にしておく
        user1 = "不明な発話"
        print(f"USER: {user1}")
        core.on_transcript(call_id, user1, is_final=True)
        state = core._get_session_state(call_id)
        unclear_streak_1 = state.get("unclear_streak", 0)
        print(f"TURN1 unclear_streak={unclear_streak_1}")
        assert unclear_streak_1 == 1, f"TURN1 unclear_streak should be 1, got {unclear_streak_1}"
        
        # 明示的なハンドオフ要求 → 既存の HANDOFF_REQUEST が優先される
        user2 = "担当者"
        print(f"USER: {user2}")
        core.on_transcript(call_id, user2, is_final=True)
        state = core._get_session_state(call_id)
        meta = state.get("meta", {})
        t2 = capture.last_templates()
        print(f"TURN2 templates={t2}")
        print(f"TURN2 meta={meta}")
        assert t2 == ["0604"], f"TURN2 templates should be ['0604'], got {t2}"
        # 明示的なハンドオフ要求では meta.reason_for_handoff が auto_unclear にならない
        assert meta.get("reason_for_handoff") != "auto_unclear", f"meta.reason_for_handoff should not be 'auto_unclear' for explicit handoff request, got {meta.get('reason_for_handoff')}"
    finally:
        restore_intent_rules(orig_ai, orig_ir)
        restore_intent_rules_for_unclear_test(orig_classify, orig_select)

# ==== エントリポイント ====
def main() -> None:
    setup_logging()
    orig_ai, orig_ir = patch_intent_rules()
    orig_log = patch_call_log()
    try:
        run_case_yes()
        run_case_no()
        run_case_unclear_streak_force_handoff()
        run_case_unclear_streak_reset()
        run_case_handoff_done_reset()
        run_case_existing_handoff_non_interference()
        print("\n=== ALL HANDOFF TESTS PASSED ===")
    finally:
        restore_call_log(orig_log)
        restore_intent_rules(orig_ai, orig_ir)
if __name__ == "__main__":
    main()