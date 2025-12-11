# AICore シナリオテスト仕様書

## 概要

このドキュメントは、`AICORE_SPEC.md` と `AICORE_RISK_CASES.md` を元に、AICore の会話ロジック（特に HANDOFF 周り）のシナリオテスト仕様を定義したものです。

---

## 1. テスト観点の一覧

### 1-1. 通常フロー

- **ENTRY → QA → AFTER_085 → CLOSING → HANDOFF → HANDOFF_CONFIRM_WAIT → HANDOFF_DONE → END**
  - 正常な会話フローが期待通りに動作することを確認
  - 各 phase の遷移が正しく行われることを確認

### 1-2. HANDOFF_CONFIRM 周り

- **YES（明示的な「はい、お願いします」など）**
  - 明確な肯定応答で転送が実行されることを確認
  - カバー: 通常フロー

- **NO（「いや、大丈夫です」「結構です」など）**
  - 明確な否定応答で転送が実行されず、END に遷移することを確認
  - カバー: 通常フロー

- **あいまい応答（R2, R7 に該当）**
  - 「あ、じゃあそれで」「うーん、まあ、いいかな」などの曖昧な応答
  - retry=0 の場合は 0604 を再提示
  - retry>=1 の場合は安全側で転送
  - カバー: R2, R7

- **「はい + 新トピック」系（R1, R9, R12）**
  - 「はい、料金の話なんですけど」「はい、でもその前に質問があります」など
  - 現状は HANDOFF_YES として誤判定される
  - カバー: R1, R9, R12

### 1-3. 自動ハンドオフ発火

- **unclear_streak>=2 のケース（R3）**
  - 「よくわかりません（110）」が2回連続で選ばれた場合
  - 自動的に HANDOFF_REQUEST に変更され、0604 が提示される
  - 直後の拒否が正しく処理されることを確認
  - カバー: R3

- **not_heard_streak>=2 のケース（R8）**
  - 「もう一度お願いします（110）」が2回連続で選ばれた場合
  - 自動的に 0604 が提示される
  - 直後の拒否が正しく処理されることを確認
  - カバー: R8

### 1-4. 転送フラグ・状態不整合

- **転送実行済みで再度 HANDOFF_REQUEST（R4, R11）**
  - handoff_state=done かつ transfer_executed=True の状態で HANDOFF_REQUEST が来た場合
  - 現状は transfer_executed が False にリセットされる
  - カバー: R4, R11

- **phase=END なのに transfer_requested=True など（R5, R10）**
  - phase=END に遷移したが、transfer_requested が True のままの場合
  - 自動切断タイマーがセットされない可能性がある
  - カバー: R5, R10

### 1-5. 時間稼ぎ的な発話（R6）

- **「えーっと、ちょっと待ってください」など**
  - ユーザが考えている時間を取ろうとしている場合
  - 現状はすぐに 0604 を再提示される
  - カバー: R6

---

## 2. 危険パターン R1〜R5 のシナリオ定義

### Scenario R1: 「はい + 新トピック」で誤転送しないこと

```text
初期状態:
  phase=HANDOFF_CONFIRM_WAIT
  handoff_state=confirming
  handoff_retry_count=0
  transfer_requested=False
  unclear_streak=0
  not_heard_streak=0

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示済み、ここは前提でもOK）
  U2: 「はい、料金の話なんですけど」

期待値:
  - 現状挙動: 
      - intent: UNKNOWN → HANDOFF_YES（「はい」が含まれるため）
      - テンプレ: 081+082
      - phase: HANDOFF_DONE
      - handoff_state: done
      - transfer_requested: True
      - transfer_executed: True
  - 望ましい挙動案: 
      - HANDOFF_YES ではなく UNKNOWN として扱う
      - handoff_retry_count を増やす or QA フェーズに戻す
  - テストとして確認したいポイント:
      - 現行コードでは 081+082 が返っていること（現状の再現）
      - 「はい」の後に新トピック（料金、サービス、価格など）が続く場合は誤判定されること
```

### Scenario R2: 曖昧な肯定表現で安全側に転送される

```text
初期状態:
  phase=HANDOFF_CONFIRM_WAIT
  handoff_state=confirming
  handoff_retry_count=1
  transfer_requested=False
  unclear_streak=0
  not_heard_streak=0

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示済み）
  U2: 「えーっと...」（UNKNOWN → 0604 再提示、handoff_retry_count=1）
  U3: 「あ、じゃあそれで」

期待値:
  - 現状挙動:
      - intent: UNKNOWN（曖昧な肯定表現）
      - テンプレ: 081+082（安全側で転送）
      - phase: HANDOFF_DONE
      - handoff_state: done
      - transfer_requested: True
      - transfer_executed: True
  - 望ましい挙動案:
      - 曖昧な肯定表現は明確な YES/NO 判定を避け、もう一度確認プロンプト（0604）を出す
  - テストとして確認したいポイント:
      - 現行コードでは retry>=1 の場合、安全側で転送されること（現状の再現）
      - 「あ、じゃあそれで」のような曖昧な表現でも転送されること
```

### Scenario R3: 自動ハンドオフ発火直後の拒否が無視される

```text
初期状態:
  phase=QA
  handoff_state=idle
  unclear_streak=2
  not_heard_streak=0
  handoff_prompt_sent=False

ユーザ発話シーケンス:
  U1: （不明瞭な発話 → 110 が選ばれる、unclear_streak=1）
  U2: （不明瞭な発話 → 110 が選ばれる、unclear_streak=2）
  U3: （自動ハンドオフ発火 → 0604 提示）
  U4: 「いや、やっぱりいいです」

期待値:
  - 現状挙動:
      - U3 時点: intent が強制的に HANDOFF_REQUEST に変更され、0604 が提示される
      - U4 時点: intent: UNKNOWN / END_CALL → HANDOFF_NO
      - テンプレ: 086+087
      - phase: END
      - handoff_state: done
  - 望ましい挙動案:
      - 自動ハンドオフ発火直後の拒否は、0604 を出さずに即座に END に遷移する
  - テストとして確認したいポイント:
      - unclear_streak>=2 で自動ハンドオフ発火すること（現状の再現）
      - 自動ハンドオフ発火直後に拒否しても、一度 0604 が出てから拒否処理になること
```

### Scenario R4: 転送実行後に再度ハンドオフ要求が来た場合のフラグリセット

```text
初期状態:
  phase=AFTER_085
  handoff_state=done
  transfer_executed=True
  transfer_requested=True
  handoff_completed=True

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示、転送実行済み）
  U2: 「やっぱり担当者お願いします」

期待値:
  - 現状挙動:
      - intent: HANDOFF_REQUEST
      - テンプレ: 0604
      - handoff_state: done→confirming
      - transfer_executed: True→False（リセット）
      - transfer_requested: True→False
  - 望ましい挙動案:
      - handoff_state=done かつ transfer_executed=True の状態で HANDOFF_REQUEST が来た場合は、「既に転送処理中です」などのメッセージを返し、0604 を出さない
  - テストとして確認したいポイント:
      - 現行コードでは transfer_executed が False にリセットされること（現状の再現）
      - 既に転送が実行された状態で再度ハンドオフ要求が来た場合、転送フラグがリセットされること
```

### Scenario R5: phase=END なのに転送フラグが中途半端に立っている

```text
初期状態:
  phase=END
  transfer_requested=True
  transfer_executed=False
  handoff_state=done

ユーザ発話シーケンス:
  （発話なし、または END_CALL）

期待値:
  - 現状挙動:
      - phase=END に遷移したとき、transfer_requested_flag が False の場合のみ自動切断をセット
      - transfer_requested=True の場合は自動切断がセットされない
  - 望ましい挙動案:
      - phase=END に遷移したとき、transfer_requested=True でも transfer_executed=False の場合は、転送を実行するか、または自動切断タイマーをセットする
  - テストとして確認したいポイント:
      - phase=END なのに transfer_requested=True の場合、自動切断タイマーがセットされないこと（現状の再現）
      - 状態の不整合が発生していること
```

---

## 3. 危険パターン R6〜R12 のシナリオ定義（参考）

### Scenario R6: 時間稼ぎ的な発話

```text
初期状態:
  phase=HANDOFF_CONFIRM_WAIT
  handoff_state=confirming
  handoff_retry_count=0
  transfer_requested=False

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示済み）
  U2: 「えーっと、ちょっと待ってください」

期待値:
  - 現状挙動:
      - intent: UNKNOWN（時間稼ぎ的な発話）
      - テンプレ: 0604（retry=0 なので再確認）
      - handoff_retry_count: 0→1
      - phase: HANDOFF_CONFIRM_WAIT
  - 望ましい挙動案:
      - 時間稼ぎ的な発話は、0604 を再提示せず、数秒待ってから再確認する
  - テストとして確認したいポイント:
      - 現行コードではすぐに 0604 を再提示されること（現状の再現）
```

### Scenario R7: 曖昧な肯定表現（retry=1）

```text
初期状態:
  phase=HANDOFF_CONFIRM_WAIT
  handoff_state=confirming
  handoff_retry_count=1
  transfer_requested=False

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示済み）
  U2: 「えーっと...」（UNKNOWN → 0604 再提示、handoff_retry_count=1）
  U3: 「うーん、まあ、いいかな」

期待値:
  - 現状挙動:
      - intent: UNKNOWN（曖昧な肯定表現）
      - テンプレ: 081+082（安全側で転送）
      - phase: HANDOFF_DONE
      - transfer_requested: True
  - テストとして確認したいポイント:
      - 現行コードでは retry>=1 の場合、安全側で転送されること（現状の再現）
```

### Scenario R8: not_heard_streak>=2 で自動ハンドオフ発火

```text
初期状態:
  phase=QA
  handoff_state=idle
  not_heard_streak=2
  unclear_streak=0

ユーザ発話シーケンス:
  U1: （聞き取れない発話 → 110 が選ばれる、not_heard_streak=1）
  U2: （聞き取れない発話 → 110 が選ばれる、not_heard_streak=2）
  U3: （自動ハンドオフ発火 → 0604 提示）
  U4: 「いや、大丈夫です」

期待値:
  - 現状挙動:
      - U3 時点: not_heard_streak>=2 で自動ハンドオフ発火、0604 が提示される
      - U4 時点: intent: UNKNOWN / END_CALL → HANDOFF_NO
      - テンプレ: 086+087
      - phase: END
  - テストとして確認したいポイント:
      - not_heard_streak>=2 で自動ハンドオフ発火すること（現状の再現）
```

### Scenario R9: 「はい、でもその前に質問があります」

```text
初期状態:
  phase=HANDOFF_CONFIRM_WAIT
  handoff_state=confirming
  handoff_retry_count=0
  transfer_requested=False

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示済み）
  U2: 「はい、でもその前に質問があります」

期待値:
  - 現状挙動:
      - intent: UNKNOWN → HANDOFF_YES（「はい」が含まれるため）
      - テンプレ: 081+082
      - phase: HANDOFF_DONE
      - transfer_requested: True
  - テストとして確認したいポイント:
      - 現行コードでは「はい」の後に「でも」「その前に」「質問」が続いても HANDOFF_YES として判定されること（現状の再現）
```

### Scenario R10: phase=END なのに handoff_state=done

```text
初期状態:
  phase=END
  transfer_requested=False
  transfer_executed=False
  handoff_state=done

ユーザ発話シーケンス:
  （発話なし）

期待値:
  - 現状挙動:
      - 自動切断タイマーがセットされる（transfer_requested=False のため）
      - 状態の不整合（phase=END なのに handoff_state=done）が発生しているが、自動切断は正常に動作する
  - テストとして確認したいポイント:
      - 状態の不整合が発生していること（現状の再現）
```

### Scenario R11: 転送実行済みで拒否

```text
初期状態:
  phase=HANDOFF_DONE
  handoff_state=done
  transfer_executed=True
  transfer_requested=True

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 転送実行済み）
  U2: 「あ、やっぱりいいです」

期待値:
  - 現状挙動:
      - intent: UNKNOWN / END_CALL
      - テンプレ: 通常のQAフロー（handoff_state=done なので 0604/104 は出さない）
      - phase: AFTER_085 など
  - テストとして確認したいポイント:
      - 既に転送が実行された状態でユーザが拒否しても、転送を取り消せないこと（現状の再現）
```

### Scenario R12: 「はい、お願いします。あ、でも料金について聞きたいんですけど」

```text
初期状態:
  phase=HANDOFF_CONFIRM_WAIT
  handoff_state=confirming
  handoff_retry_count=0
  transfer_requested=False

ユーザ発話シーケンス:
  U1: 「担当者に変わってもらえますか？」（HANDOFF_REQUEST → 0604 提示済み）
  U2: 「はい、お願いします。あ、でも料金について聞きたいんですけど」

期待値:
  - 現状挙動:
      - intent: HANDOFF_YES（「はい、お願いします」が含まれるため）
      - テンプレ: 081+082
      - phase: HANDOFF_DONE
      - transfer_requested: True
  - テストとして確認したいポイント:
      - 現行コードでは「はい、お願いします」の後に「でも」「聞きたい」が続いても HANDOFF_YES として判定されること（現状の再現）
```

---

## 4. テスト実装方針

### 4-1. テスト環境

- AICore は `init_clients=False` で生成し、ASR/TTS などの外部依存は使わない
- `on_transcript` を直接呼び出すか、内部の `_generate_reply` / `_run_conversation_flow` を直接叩く
- 実際に喋らせる必要はなく、`session_states[call_id]` と `template_ids` / `intent` を検証する

### 4-2. テストヘルパー

- `TemplateCapture` クラス: `tts_callback` をキャプチャしてテンプレートIDを取得
- `make_core()` 関数: テスト用の AICore インスタンスを生成
- `dump_state()` 関数: 状態をダンプしてデバッグに使用

### 4-3. アサーション方針

- 現状の挙動を固定化するテストとする（将来のリファクタ前の期待値）
- 「望ましい挙動」はまだ実装しないので、あくまで「今のコードがどう動いているか」を確認する
- 各シナリオについて、以下を検証:
  - `phase` の遷移
  - `handoff_state` の変化
  - `transfer_requested` / `transfer_executed` の状態
  - `template_ids` の内容
  - `intent` の判定結果

---

**注意**: このドキュメントはテスト仕様を定義したものです。実際のテストコードは `tests/test_ai_core_handoff.py` に実装されます。

