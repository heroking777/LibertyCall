# AICore リファクタ方針メモ

## 1. 目的と前提

### 現状課題の整理

AICore の会話ロジックは、以下の課題を抱えています:

1. **状態管理の複雑さ**: `session_states[call_id]` に12個以上のキーがフラットに格納されており、責務が分散している
   - `phase`（会話フェーズ）: ENTRY → QA → AFTER_085 → CLOSING → HANDOFF → HANDOFF_CONFIRM_WAIT → HANDOFF_DONE → END
   - `handoff_state`（ハンドオフ状態）: idle → confirming → done
   - `*_streak`（連続カウンタ）: `unclear_streak`, `not_heard_streak`
   - `transfer_*`（転送フラグ）: `transfer_requested`, `transfer_executed`
   - `meta`（メタ情報）: 自動ハンドオフ発火時の理由など

2. **HANDOFF フローのデリケートさ**: 「はい」「お願いします」の解釈が intent / phase / handoff_state に依存して変わる
   - `_handle_handoff_confirm` で UNKNOWN/NOT_HEARD でも「はい」が含まれていれば HANDOFF_YES として扱われる
   - 「はい、料金の話なんですけど」のような発話でも誤判定される（R1, R9, R12）
   - あいまいな肯定表現（「あ、じゃあそれで」「うーん、まあ、いいかな」）でも安全側で転送される（R2, R7）

3. **リスクパターンの集中**: 12個の危険パターン（R1〜R12）の多くが `_handle_handoff_confirm` 周りに集中
   - R1, R2, R7, R9, R12: HANDOFF_CONFIRM 時の YES/NO 判定の問題
   - R3, R8: 自動ハンドオフ発火（unclear_streak / not_heard_streak）のポリシー
   - R4, R5, R11: 転送フラグの不整合や二重実行防止の問題

### リファクタ方針の位置づけ

このリファクタ方針は、**ローンチ前に全部やる前提ではなく**、段階的に進めるためのプランです。現状のコードは動作しており、リファクタは「保守性向上」と「リスクパターン解消」を目的としています。

---

## 2. 現状の構造整理

### 状態管理の現状

- `session_states[call_id]` に状態がフラットに積まれている
  - 12個以上のキーが `Dict[str, Any]` として管理されている
  - キー名の typo や初期化漏れが発生しやすい
  - 状態遷移のロジックが複数のメソッドに分散している

- 責務のざっくり整理:
  - `phase`: 会話全体のフェーズ（ENTRY → QA → AFTER_085 → CLOSING → HANDOFF → HANDOFF_CONFIRM_WAIT → HANDOFF_DONE → END）
  - `handoff_state`: ハンドオフ（転送）の状態（idle → confirming → done）
  - `*_streak`: 連続カウンタ（unclear_streak: AIが理解できない回数、not_heard_streak: 聞き取れない回数）
  - `transfer_*`: 転送関連フラグ（transfer_requested: 転送要求、transfer_executed: 転送実行済み）
  - `meta`: メタ情報（自動ハンドオフ発火時の理由など）

### HANDOFF ロジックの現状

- `_generate_reply` に HANDOFF 関連の入口ロジックが集中
  - unclear_streak>=2 で強制的に HANDOFF_REQUEST に変更（1534-1550行目）
  - HANDOFF_YES が confirming 以外で来た場合は HANDOFF_REQUEST にダウングレード（1552-1559行目）
  - HANDOFF_REQUEST は handoff_state に関係なく常に 0604 を返す（1568-1591行目）

- `_handle_handoff_confirm` が YES/NO/あいまい/安全側転送・転送コールバックまで全部見る
  - YES 判定強化: UNKNOWN/NOT_HEARD でも「はい」が含まれていれば HANDOFF_YES（1219-1249行目）
  - NO 判定強化: UNKNOWN/END_CALL/NOT_HEARD でも NO 系フレーズがあれば HANDOFF_NO（1251-1268行目）
  - あいまい応答の処理: retry=0 なら 0604 再提示、retry>=1 なら安全側で転送（1363-1419行目）
  - transfer_callback の実行もここで行う（1288-1316行目）

- `_handle_handoff_phase` が phase 更新と transfer_callback の二重実行防止を担当
  - `_handle_handoff_confirm` の結果に基づいて phase を更新（1439-1462行目）
  - transfer_callback を再度呼ぶ可能性がある（1444-1455行目）

---

## 3. リファクタの方向性（大枠）

### 3-1. 状態オブジェクト化

#### 狙い

`session_states[call_id]` にフラットな dict で生状態を持つのをやめ、`ConversationState` / `HandoffState` のような小さなクラスにまとめることで、フィールド更新の責務を一箇所に寄せたい。

#### 案

```python
# 会話全体の状態
class ConversationState:
    phase: str  # ENTRY, QA, AFTER_085, CLOSING, HANDOFF, HANDOFF_CONFIRM_WAIT, HANDOFF_DONE, END
    last_intent: Optional[str]
    not_heard_streak: int
    unclear_streak: int
    meta: Dict[str, Any]
    
    def to_qa(self) -> None:
        """QA フェーズに遷移"""
    def to_end(self) -> None:
        """END フェーズに遷移"""
    def increment_unclear_streak(self) -> None:
        """unclear_streak をインクリメント"""
    def reset_unclear_streak(self) -> None:
        """unclear_streak をリセット"""

# ハンドオフ専用の状態
class HandoffState:
    handoff_state: str  # idle, confirming, done
    handoff_retry_count: int
    transfer_requested: bool
    transfer_executed: bool
    handoff_completed: bool
    handoff_prompt_sent: bool
    
    def start_confirming(self) -> None:
        """confirming 状態に遷移"""
    def mark_transfer_done(self) -> None:
        """転送完了をマーク"""
    def increment_retry(self) -> None:
        """retry_count をインクリメント"""
```

#### ポイント

- 既存の `session_states[call_id]` は暫定的に `ConversationContext` みたいなラッパで返す形にして、既存コードを一気に書き換えないステップも書く
  - 例: `_get_session_state` で `ConversationContext` を返すが、内部的には dict を保持
  - `ConversationContext` は `__getitem__` / `__setitem__` を実装して、既存の `state["phase"]` 形式でもアクセス可能にする
  - 順次 `state.phase` 形式に移行していく

---

### 3-2. HANDOFF 用ステートマシンの切り出し

#### 狙い

`_handle_handoff_confirm` の責務が重く、YES/NO 判定、retry 管理、テンプレ決定、callback 呼び出しまで抱えているので、「HandoffDecisionEngine」のような小さなクラスに切り出して見通しを良くしたい。

#### 案

```python
class HandoffDecisionResult:
    """ハンドオフ決定の結果"""
    templates: List[str]
    new_handoff_state: str  # idle, confirming, done
    new_phase: Optional[str]  # None の場合は phase を変更しない
    should_request_transfer: bool
    end_phase: Optional[str]  # END に遷移する場合
    meta: Dict[str, Any]

class HandoffStateMachine:
    """ハンドオフ専用のステートマシン"""
    
    def __init__(self, handoff_state: HandoffState):
        self.state = handoff_state
    
    def decide(
        self,
        intent: str,
        raw_text: str,
        normalized_text: str,
        conv_state: ConversationState
    ) -> HandoffDecisionResult:
        """
        ハンドオフ決定ロジック
        
        - YES/NO 判定（「はい + 新トピック」などのパターンも考慮）
        - retry 管理
        - テンプレ決定
        - 転送要求の判定
        """
        # R1/R9/R12 対応: 「はい + 新トピック」の検出
        if self._has_yes_with_followup_topic(intent, normalized_text):
            return self._handle_ambiguous_response(intent, normalized_text)
        
        # R2/R7 対応: 曖昧な肯定表現の検出
        if self._is_ambiguous_yes(intent, normalized_text):
            return self._handle_ambiguous_response(intent, normalized_text)
        
        # 通常の YES/NO 判定
        if intent == "HANDOFF_YES":
            return self._handle_yes()
        elif intent == "HANDOFF_NO":
            return self._handle_no()
        else:
            return self._handle_ambiguous_response(intent, normalized_text)
    
    def _has_yes_with_followup_topic(self, intent: str, normalized_text: str) -> bool:
        """「はい + 新トピック」パターンの検出（R1, R9, R12 対応）"""
        # 「はい」が含まれているが、その後に「でも」「その前に」「質問」「料金」などが続く
        pass
    
    def _is_ambiguous_yes(self, intent: str, normalized_text: str) -> bool:
        """曖昧な肯定表現の検出（R2, R7 対応）"""
        # 「あ、じゃあそれで」「うーん、まあ、いいかな」など
        pass
```

#### ポイント

- `AICORE_TEST_SCENARIOS.md` と `test_ai_core_handoff.py` のテストシナリオを、このステートマシンに対するユニットテストとしても再利用できる構造を意識する
  - `HandoffStateMachine` を独立してテストできるようにする
  - R1〜R5 のシナリオを、ステートマシンの入力・出力として定義できるようにする

---

### 3-3. 「転送決定」と「転送実行」の責務分離

#### 狙い

今は `_handle_handoff_confirm` / `_handle_handoff_phase` / `on_transcript` それぞれの中で transfer_callback を呼ぶ可能性があり、`transfer_executed` でもガードしている状態。 「いつ `transfer_requested=True` にするか」と「いつ `transfer_callback` を実際に叩くか」を分けることで、二重実行・未実行を避けたい。

#### 案

```python
class HandoffDecisionResult:
    """ハンドオフ決定の結果"""
    templates: List[str]
    new_handoff_state: str
    new_phase: Optional[str]
    should_request_transfer: bool  # 転送を要求するかどうか（決定のみ）
    # transfer_callback の実行は含まない

class AICore:
    def _trigger_transfer_if_needed(self, call_id: str, state: Dict[str, Any]) -> None:
        """
        転送を実行する（1箇所に集約）
        
        - transfer_requested=True かつ transfer_executed=False の場合のみ実行
        - 実行後、transfer_executed=True に設定
        """
        if state.get("transfer_requested") and not state.get("transfer_executed"):
            if self.transfer_callback:
                try:
                    self.transfer_callback(call_id)
                    state["transfer_executed"] = True
                except Exception as e:
                    self.logger.exception("TRANSFER_CALLBACK_ERROR: %s", e)
```

#### ポイント

- R4 / R5 / R11 あたりの危険パターンに効くことをコメントで触れておく
  - R4: 転送実行済みで再度 HANDOFF_REQUEST が来た場合、`transfer_executed=True` のチェックで二重実行を防ぐ
  - R5: phase=END なのに transfer_requested=True の場合、`_trigger_transfer_if_needed` で転送を実行するか、自動切断タイマーをセットする
  - R11: 転送実行済みで拒否が来た場合、`transfer_executed=True` のチェックで転送を取り消せないことを明確にする

---

### 3-4. 「迷子（unclear / not_heard）」ハンドリングの明文化

#### 狙い

`unclear_streak` / `not_heard_streak` がハンドオフ発火や 0604 提示に直結しているが、ロジックが `_generate_reply` の中でバラバラに書かれている。 ここのポリシー（何回まではリトライ / 何回でハンドオフ提案）は 1箇所に集約したい。

#### 案

```python
class MisunderstandingGuard:
    """迷子（理解不能・聞き取れない）状態のガード"""
    
    # ポリシー定数
    UNCLEAR_STREAK_THRESHOLD = 2  # unclear_streak がこの値以上で自動ハンドオフ発火
    NOT_HEARD_STREAK_THRESHOLD = 2  # not_heard_streak がこの値以上で自動ハンドオフ発火
    
    def should_force_handoff(
        self,
        unclear_streak: int,
        not_heard_streak: int,
        handoff_state: str,
        intent: str
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        自動ハンドオフ発火を判定
        
        戻り値:
            (should_force, meta)
            - should_force: True の場合は強制的に HANDOFF_REQUEST に変更
            - meta: 自動ハンドオフ発火時のメタ情報（reason_for_handoff など）
        """
        # unclear_streak>=2 で自動ハンドオフ発火（R3 対応）
        if unclear_streak >= self.UNCLEAR_STREAK_THRESHOLD:
            if handoff_state in ("idle", "done") and intent not in ("HANDOFF_REQUEST", "HANDOFF_YES", "HANDOFF_NO"):
                return True, {"reason_for_handoff": "auto_unclear", "unclear_streak_at_trigger": unclear_streak}
        
        # not_heard_streak>=2 で自動ハンドオフ発火（R8 対応）
        if not_heard_streak >= self.NOT_HEARD_STREAK_THRESHOLD:
            if handoff_state == "idle":
                return True, {"reason_for_handoff": "auto_not_heard", "not_heard_streak_at_trigger": not_heard_streak}
        
        return False, None
    
    def should_force_0604(
        self,
        unclear_streak: int,
        not_heard_streak: int,
        handoff_state: str,
        handoff_prompt_sent: bool
    ) -> bool:
        """0604 を強制的に提示すべきか判定"""
        # not_heard_streak>=2 で 0604 を提示
        if not_heard_streak >= self.NOT_HEARD_STREAK_THRESHOLD and handoff_state == "idle":
            return True
        return False
```

#### ポイント

- R3 / R8 を例に、「ポリシーを書き換えるだけで挙動を変えられる」形を目指す
  - `UNCLEAR_STREAK_THRESHOLD = 2` を `3` に変更するだけで、自動ハンドオフ発火のタイミングを変えられる
  - ポリシーを1箇所に集約することで、テストやデバッグが容易になる

---

## 4. フェーズ分割プラン（段階的導入案）

### 第1段: 状態オブジェクトの導入（互換レイヤー付き）

#### 内容

- `ConversationState` / `HandoffState`（名称は案でOK）を定義
- `_get_session_state` で dict を直接返すのではなく、薄いラッパオブジェクトを返す方式に変更
  - 内部的にはまだ dict を使ってよい
  - 既存コードは `state["phase"]` などを使い続けられるが、順次 `state.phase` に寄せていくイメージ

#### リスク

- 最初の導入時にキー名のtypoなどでコケる可能性
- 既存コードとの互換性を保つ必要がある

#### カバーするテスト

- 既存の `tests/test_ai_core_handoff.py` とシナリオテスト一式
- 状態オブジェクトの getter/setter のテスト

#### タイミング

- **ローンチ前**: 可能であれば実施（保守性向上のため）
- **ローンチ後**: 必須ではないが、優先度高め

---

### 第2段: HANDOFF ステートマシンの分離

#### 内容

- `_handle_handoff_confirm` の中身を、専用クラス（例: `HandoffStateMachine`）に移管
- AICORE_RISK_CASES.md の R1〜R5 を、そのステートマシンに対するユニットテストでカバー
- 「はい + 新トピック」パターン（R1, R9, R12）の改善をこのクラスに実装

#### リスク

- YES/NO 判定とテンプレ決定の条件漏れ
- 既存の挙動を変えてしまう可能性

#### カバーするテスト

- 既存のハンドオフテスト + 手動通話テスト（本番トラフィックに近い対話ログの確認）
- `HandoffStateMachine` に対するユニットテスト（R1〜R5 のシナリオ）

#### タイミング

- **ローンチ前**: R1/R2/R3 に効く条件分岐の整理は実施推奨（ユーザー体験向上のため）
- **ローンチ後**: R4/R5 などの細かい改善は安定期に実施

---

### 第3段: 転送決定/実行の責務分離 + 迷子ガードの切り出し

#### 内容

- transfer_callback の呼び出しを `_trigger_transfer_if_needed` に一本化
- `unclear_streak` / `not_heard_streak` 用のポリシークラス（仮: `MisunderstandingGuard`）導入

#### 優先度

- **R3/R5/R8 のリスクが大きい場合はローンチ前**:
  - R3: 自動ハンドオフ発火直後の拒否が無視される → ユーザー体験に直結
  - R5: phase=END なのに転送フラグが中途半端 → 通話が宙ぶらりんになる可能性
  - R8: not_heard_streak>=2 で自動ハンドオフ発火 → ユーザー体験に直結

- **そうでなければローンチ後の安定期に回す**:
  - 迷子ガードの切り出しは、ポリシー変更の柔軟性を高めるため、優先度は中程度
  - 転送決定/実行の責務分離は、R4/R11 などの細かい改善のため、優先度は低め

#### タイミング

- **ローンチ前**: R3/R5/R8 対応は実施推奨
- **ローンチ後**: その他の改善は安定期に実施

---

## 5. 優先度とタイミング（ローンチ前にやる範囲）

### ローンチ前にやるべき最低ライン

1. **第1段の状態オブジェクト導入（互換レイヤー付き）**
   - `ConversationState` / `HandoffState` の定義
   - `_get_session_state` でラッパオブジェクトを返す（既存コードとの互換性を保つ）
   - 状態遷移メソッドの実装（`to_qa()`, `to_end()`, `start_confirming()` など）

2. **第2段の HANDOFF ステートマシンのクラス設計**
   - `HandoffStateMachine` の定義と基本ロジックの移管
   - R1/R2/R3 に効く条件分岐の整理
     - R1: 「はい + 新トピック」パターンの検出
     - R2: 曖昧な肯定表現の検出
     - R3: 自動ハンドオフ発火直後の拒否処理

3. **第3段の転送決定/実行の責務分離（R3/R5/R8 対応）**
   - `_trigger_transfer_if_needed` への集約
   - `MisunderstandingGuard` の導入（R3/R8 対応）
   - phase=END 時の状態クリーンアップ（R5 対応）

### ローンチ後の安定期に回してよいもの

1. **MisunderstandingGuard の完全な切り出し**
   - ポリシー変更の柔軟性を高めるため、優先度は中程度
   - ローンチ前でも可能だが、必須ではない

2. **転送キャンセル機構（R11 対応）**
   - 既に転送が実行された状態でユーザが拒否した場合の処理
   - 優先度は低め（現状でも `transfer_executed` のチェックで二重実行は防げている）

3. **時間稼ぎ的な発話の処理（R6 対応）**
   - 「えーっと、ちょっと待ってください」などの発話に対する処理
   - 優先度は低め（現状でも動作している）

4. **状態の整合性チェック強化（R10 対応）**
   - phase=END なのに handoff_state=done などの不整合チェック
   - 優先度は低め（現状でも動作している）

### ASR/TTS との絡み

- **AICore 側のリファクタは ASR/TTS とはほぼ独立して進められる**
  - 状態管理と HANDOFF ロジックは、ASR/TTS の実装に依存しない
  - `init_clients=False` でテストできるため、段階的な導入が可能

- **音声認識エラー時の ASR_ERROR ハンドラ周りはセットで考える必要がある**
  - `_on_asr_error` で転送フラグを設定している（1905-1928行目）
  - リファクタ時は、`_on_asr_error` も `_trigger_transfer_if_needed` を使うように統一する

---

## 6. まとめ

このリファクタ方針は、段階的な導入を前提としており、ローンチ前に全部やる必要はありません。優先度の高いもの（R1/R2/R3/R5/R8 対応）をローンチ前に実施し、その他の改善はローンチ後の安定期に実施することを推奨します。

状態オブジェクト化と HANDOFF ステートマシンの分離により、コードの見通しが良くなり、テストやデバッグが容易になります。また、リスクパターン（R1〜R12）の多くが解消されることが期待されます。

