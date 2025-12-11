# 危険パターン一覧（AICore HANDOFF / phase 周り）

## 概要

このドキュメントは、`ai_core.py` と `AICORE_SPEC.md` を元に、事故りそうな状態×発話パターンと現状挙動 / 望ましい挙動を列挙したものです。

**注意**: このドキュメントは分析結果のみを記載しており、コードの変更は含まれていません。

---

## 危険パターン一覧表

| ID | 状態 (phase / handoff_state / handoff_retry_count / transfer_requested / unclear_streak / not_heard_streak 他) | ユーザ発話例 | intent 判定（現状） | 現状の挙動（テンプレID / phase 遷移 / フラグ変化） | 想定されるリスク | 望ましい挙動（高レベル） |
|----|----------------------------------------------------------------------------------------------------------------|-------------|-------------------|--------------------------------------------------|----------------|----------------------|
| R1 | phase=HANDOFF_CONFIRM_WAIT, handoff_state=confirming, handoff_retry_count=0, transfer_requested=False, unclear_streak=0, not_heard_streak=0 | 「はい、料金の話なんですけど」 | UNKNOWN → HANDOFF_YES（「はい」が含まれるため） | テンプレ: 081+082 / phase: HANDOFF_DONE / transfer_requested=True / transfer_executed=True | ユーザは「はい」で質問を始めようとしたのに、転送されてしまう。「急に転送された」と感じる。 | 「はい」の後に新トピック（料金、サービス、価格など）が続く場合は、HANDOFF_YES ではなく UNKNOWN として扱い、0604 を再提示するか、通常のQAフローに戻す。 |
| R2 | phase=HANDOFF_CONFIRM_WAIT, handoff_state=confirming, handoff_retry_count=1, transfer_requested=False, unclear_streak=0, not_heard_streak=0 | 「あ、じゃあそれで」 | UNKNOWN（曖昧な肯定表現） | テンプレ: 081+082 / phase: HANDOFF_DONE / handoff_state=done / transfer_requested=True / transfer_executed=True（安全側で転送） | ユーザの意図が不明確なまま転送される。ユーザは「それで」が何を指すのか分からず混乱する。 | 曖昧な肯定表現（「それで」「あ、じゃあ」など）は、明確な YES/NO 判定を避け、もう一度確認プロンプト（0604）を出す。または、ユーザに「はい」か「いいえ」で答えるよう促す。 |
| R3 | phase=QA, handoff_state=idle, unclear_streak=2, not_heard_streak=0, handoff_prompt_sent=False | unclear_streak>=2 で自動ハンドオフ発火後、「いや、やっぱりいいです」 | HANDOFF_REQUEST（強制） → その後 UNKNOWN / END_CALL | テンプレ: 0604（自動ハンドオフ発火） → その後 086+087（NO判定） / phase: END / handoff_state=done | 自動ハンドオフ発火直後にユーザが拒否しても、一度 0604 が出てから拒否処理になる。ユーザは「勝手にハンドオフ提案された」と感じる。 | unclear_streak>=2 で自動ハンドオフ発火する前に、ユーザに「もう一度お話しいただけますか？」などの確認を出す。または、自動ハンドオフ発火直後の拒否は、0604 を出さずに即座に END に遷移する。 |
| R4 | phase=AFTER_085, handoff_state=done, transfer_executed=True, transfer_requested=True, handoff_completed=True | 「やっぱり担当者お願いします」 | HANDOFF_REQUEST | テンプレ: 0604 / handoff_state: done→confirming / transfer_executed: True→False（リセット） / transfer_requested: True→False | 既に転送が実行された状態で再度ハンドオフ要求が来た場合、転送フラグがリセットされる。転送が二重実行される可能性がある（ただし transfer_executed のチェックで防がれる）。 | handoff_state=done かつ transfer_executed=True の状態で HANDOFF_REQUEST が来た場合は、「既に転送処理中です」などのメッセージを返し、0604 を出さない。または、転送フラグをリセットせず、既存の転送状態を維持する。 |
| R5 | phase=END, transfer_requested=True, transfer_executed=False, handoff_state=done | （何らかの理由で phase=END に遷移したが、transfer_requested が True のまま） | （発話なし、または END_CALL） | 自動切断タイマーがセットされない（transfer_requested=True のため） | phase=END なのに転送が実行されず、自動切断もされない。通話が宙ぶらりんになる。 | phase=END に遷移したとき、transfer_requested=True でも transfer_executed=False の場合は、転送を実行するか、または自動切断タイマーをセットする。状態の不整合を防ぐためのクリーンアップ処理を追加する。 |
| R6 | phase=HANDOFF_CONFIRM_WAIT, handoff_state=confirming, handoff_retry_count=0, transfer_requested=False | 「えーっと、ちょっと待ってください」 | UNKNOWN（時間稼ぎ的な発話） | テンプレ: 0604（retry=0 なので再確認） / handoff_retry_count: 0→1 / phase: HANDOFF_CONFIRM_WAIT | ユーザが考えている時間を取ろうとしているのに、すぐに 0604 を再提示される。ユーザは「急かされている」と感じる。 | 時間稼ぎ的な発話（「ちょっと待って」「えーっと」「考えさせて」など）は、0604 を再提示せず、数秒待ってから再確認する。または、ユーザに「お時間を取りますか？」と確認する。 |
| R7 | phase=HANDOFF_CONFIRM_WAIT, handoff_state=confirming, handoff_retry_count=1, transfer_requested=False | 「うーん、まあ、いいかな」 | UNKNOWN（曖昧な肯定表現） | テンプレ: 081+082（安全側で転送） / phase: HANDOFF_DONE / transfer_requested=True / transfer_executed=True | ユーザの意図が不明確なまま転送される。「いいかな」は肯定とも否定とも取れるが、システムは肯定として扱う。 | 曖昧な肯定表現（「いいかな」「まあ、いいか」など）は、明確な YES/NO 判定を避け、もう一度確認プロンプト（0604）を出す。または、ユーザに「はい」か「いいえ」で答えるよう促す。 |
| R8 | phase=QA, handoff_state=idle, not_heard_streak=2, unclear_streak=0 | 「もう一度お願いします」が2回連続で選ばれた後、「いや、大丈夫です」 | NOT_HEARD → その後 UNKNOWN / END_CALL | テンプレ: 0604（not_heard_streak>=2 で自動ハンドオフ発火） → その後 086+087（NO判定） / phase: END | not_heard_streak>=2 で自動ハンドオフ発火直後にユーザが拒否しても、一度 0604 が出てから拒否処理になる。ユーザは「聞き取れなかっただけで、ハンドオフは不要だった」と感じる。 | not_heard_streak>=2 で自動ハンドオフ発火する前に、ユーザに「もう一度お話しいただけますか？」などの確認を出す。または、自動ハンドオフ発火直後の拒否は、0604 を出さずに即座に END に遷移する。 |
| R9 | phase=HANDOFF_CONFIRM_WAIT, handoff_state=confirming, handoff_retry_count=0, transfer_requested=False | 「はい、でもその前に質問があります」 | UNKNOWN → HANDOFF_YES（「はい」が含まれるため） | テンプレ: 081+082 / phase: HANDOFF_DONE / transfer_requested=True / transfer_executed=True | ユーザは「はい」で質問を始めようとしたのに、転送されてしまう。「その前に質問があります」という意図が無視される。 | 「はい」の後に「でも」「その前に」「質問」などのキーワードが続く場合は、HANDOFF_YES ではなく UNKNOWN として扱い、0604 を再提示するか、通常のQAフローに戻す。 |
| R10 | phase=END, transfer_requested=False, transfer_executed=False, handoff_state=done | （HANDOFF_NO で phase=END に遷移したが、何らかの理由で handoff_state=done のまま） | （発話なし） | 自動切断タイマーがセットされる（transfer_requested=False のため） | 状態の不整合（phase=END なのに handoff_state=done）が発生しているが、自動切断は正常に動作する。 | phase=END に遷移したとき、handoff_state を適切にリセットする。または、状態の整合性チェックを追加する。 |
| R11 | phase=HANDOFF_DONE, handoff_state=done, transfer_executed=True, transfer_requested=True | 「あ、やっぱりいいです」 | UNKNOWN / END_CALL | テンプレ: 通常のQAフロー（handoff_state=done なので 0604/104 は出さない） / phase: AFTER_085 など | 既に転送が実行された状態でユーザが拒否しても、転送を取り消せない。ユーザは「やっぱりいいです」と言ったのに転送が続行される。 | handoff_state=done かつ transfer_executed=True の状態で拒否的な発話が来た場合は、「既に転送処理中です」などのメッセージを返し、転送を続行する。または、転送を取り消す仕組みを追加する。 |
| R12 | phase=HANDOFF_CONFIRM_WAIT, handoff_state=confirming, handoff_retry_count=0, transfer_requested=False | 「はい、お願いします。あ、でも料金について聞きたいんですけど」 | HANDOFF_YES（「はい、お願いします」が含まれるため） | テンプレ: 081+082 / phase: HANDOFF_DONE / transfer_requested=True / transfer_executed=True | ユーザは「はい、お願いします」と言ったが、その後に「でも料金について聞きたい」と続けている。転送されてしまう。 | 「はい、お願いします」の後に「でも」「その前に」「聞きたい」などのキーワードが続く場合は、HANDOFF_YES ではなく UNKNOWN として扱い、0604 を再提示するか、通常のQAフローに戻す。 |

---

## 特に重要な危険パターンの解説

### R1: 「はい」+ 新トピックで誤って転送される

**なぜ事故りやすいのか**

- `_handle_handoff_confirm` の 1219-1249 行目で、UNKNOWN/NOT_HEARD でも「はい」が含まれていれば HANDOFF_YES として扱われる
- 「はい、料金の話なんですけど」のような発話でも「はい」が含まれているため、HANDOFF_YES として判定される
- ユーザの意図（質問を始めようとしている）とシステムの解釈（転送への同意）が不一致

**実ユーザーから見たときにどう聞こえるか**

- 「急に転送された」「質問しようとしたのに転送された」と感じる
- システムがユーザーの発話を正しく理解していないと感じる

**望ましい挙動**

- 「はい」の後に新トピック（料金、サービス、価格など）が続く場合は、HANDOFF_YES ではなく UNKNOWN として扱い、0604 を再提示するか、通常のQAフローに戻す

---

### R2: 曖昧な肯定表現で安全側に転送される

**なぜ事故りやすいのか**

- `_handle_handoff_confirm` の 1385-1419 行目で、retry>=1 の場合は安全側で転送（081/082）される
- 「あ、じゃあそれで」のような曖昧な肯定表現でも、UNKNOWN として扱われ、retry>=1 の場合は転送される
- ユーザの意図が不明確なまま転送される

**実ユーザーから見たときにどう聞こえるか**

- 「それで」が何を指すのか分からず混乱する
- システムが勝手に転送したと感じる

**望ましい挙動**

- 曖昧な肯定表現（「それで」「あ、じゃあ」「いいかな」など）は、明確な YES/NO 判定を避け、もう一度確認プロンプト（0604）を出す。または、ユーザに「はい」か「いいえ」で答えるよう促す

---

### R3: 自動ハンドオフ発火直後の拒否が無視される

**なぜ事故りやすいのか**

- `_generate_reply` の 1534-1550 行目で、unclear_streak>=2 で強制的に HANDOFF_REQUEST に変更される
- 自動ハンドオフ発火直後にユーザが拒否しても、一度 0604 が出てから拒否処理になる
- ユーザの意図（ハンドオフ不要）が即座に反映されない

**実ユーザーから見たときにどう聞こえるか**

- 「勝手にハンドオフ提案された」と感じる
- 拒否したのに、一度確認プロンプトが出てから拒否処理になるため、システムの反応が遅いと感じる

**望ましい挙動**

- unclear_streak>=2 で自動ハンドオフ発火する前に、ユーザに「もう一度お話しいただけますか？」などの確認を出す。または、自動ハンドオフ発火直後の拒否は、0604 を出さずに即座に END に遷移する

---

### R4: 転送実行後に再度ハンドオフ要求が来た場合のフラグリセット

**なぜ事故りやすいのか**

- `_generate_reply` の 1568-1591 行目で、HANDOFF_REQUEST が来た場合は、handoff_state=done でも confirming に戻して 0604 を出す
- 1573 行目で transfer_executed も False にリセットされる
- 既に転送が実行された状態で再度ハンドオフ要求が来た場合、転送フラグがリセットされる

**実ユーザーから見たときにどう聞こえるか**

- 転送が二重実行される可能性がある（ただし transfer_executed のチェックで防がれる）
- 既に転送処理中なのに、再度確認プロンプトが出るため、混乱する

**望ましい挙動**

- handoff_state=done かつ transfer_executed=True の状態で HANDOFF_REQUEST が来た場合は、「既に転送処理中です」などのメッセージを返し、0604 を出さない。または、転送フラグをリセットせず、既存の転送状態を維持する

---

### R5: phase=END なのに転送フラグが中途半端に立っている

**なぜ事故りやすいのか**

- `on_transcript` の 2106 行目で、phase=END に遷移したとき、transfer_requested_flag が False の場合のみ自動切断をセットする
- phase=END なのに transfer_requested=True の場合は自動切断がセットされない
- 通話が宙ぶらりんになる可能性がある

**実ユーザーから見たときにどう聞こえるか**

- 通話が終了したはずなのに、転送もされず、切断もされない
- システムが正常に動作していないと感じる

**望ましい挙動**

- phase=END に遷移したとき、transfer_requested=True でも transfer_executed=False の場合は、転送を実行するか、または自動切断タイマーをセットする。状態の不整合を防ぐためのクリーンアップ処理を追加する

---

## 補足: コード上の根拠

### R1 の根拠
- `ai_core.py` 1219-1249 行目: UNKNOWN/NOT_HEARD でも「はい」が含まれていれば HANDOFF_YES として扱われる

### R2 の根拠
- `ai_core.py` 1385-1419 行目: retry>=1 の場合は安全側で転送（081/082）される

### R3 の根拠
- `ai_core.py` 1534-1550 行目: unclear_streak>=2 で強制的に HANDOFF_REQUEST に変更される

### R4 の根拠
- `ai_core.py` 1568-1591 行目: HANDOFF_REQUEST が来た場合は、handoff_state=done でも confirming に戻して 0604 を出す
- `ai_core.py` 1573 行目: transfer_executed も False にリセットされる

### R5 の根拠
- `ai_core.py` 2106 行目: phase=END に遷移したとき、transfer_requested_flag が False の場合のみ自動切断をセットする

---

**注意**: このドキュメントは分析結果のみを記載しており、コードの変更は含まれていません。実装レベルの if 分岐案などは将来のリファクタフェーズで検討してください。

