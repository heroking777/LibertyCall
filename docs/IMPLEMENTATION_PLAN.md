# 対話フロー方式 実装計画

**作成日**: 2025-12-27

---

## フェーズ1: 料金の聞き返し実装

### 1.1 新規ファイル作成

**ファイル**: `/opt/libertycall/libertycall/gateway/dialogue_flow.py`

**目的**: Intent方式とは独立した、対話フロー方式の実装

**実装内容**:
- `is_ambiguous_price_question()`: 曖昧な料金質問の判定
- `handle_price_type_response()`: 料金の種類に応じた応答
- `check_clear_price_question()`: 明確な料金質問の判定

### 1.2 テンプレート追加

**ファイル**: `/opt/libertycall/config/clients/000/default_flow.json`

**追加するテンプレート**:
```json
{
  "115": {
    "text": "どの料金でしょうか？初期費用、通話料、月額のどれですか？",
    "description": "料金の聞き返し"
  },
  "116": {
    "text": "通話料は1分あたり3円です。",
    "description": "通話料の説明"
  }
}
```

### 1.3 Phase定義追加

**ファイル**: `/opt/libertycall/config/clients/000/flow.json`

**追加するPhase**:
```json
{
  "WAITING_PRICE_TYPE": {
    "description": "料金の種類を待っている",
    "templates": [],
    "transitions": {
      "default": "QA"
    }
  }
}
```

### 1.4 テストケース作成

**ファイル**: `/opt/libertycall/libertycall/tests/test_dialogue_flow.py`

**テスト内容**:
- 曖昧な料金質問で聞き返しが返る
- 聞き返し後、ユーザーが"月額"と答えたら040が返る
- 聞き返し後、ユーザーが"初期費用"と答えたら042が返る
- 聞き返し後、ユーザーが"通話料"と答えたら116が返る

---

## フェーズ2: 機能の聞き返し実装

（フェーズ1が成功したら実装）

---

## フェーズ3: 導入の聞き返し実装

（フェーズ2が成功したら実装）

---

## 移行スケジュール

### Week 1: フェーズ1実装
- Day 1-2: dialogue_flow.py 作成
- Day 3: テンプレート追加
- Day 4: テスト作成・実行
- Day 5: 動作確認・調整

### Week 2: フェーズ2-3実装
- Day 1-2: 機能の聞き返し実装
- Day 3-4: 導入の聞き返し実装
- Day 5: 統合テスト

### Week 3: Intent方式の段階的廃止
- Day 1-2: dialogue_flow.py を ai_core.py に統合
- Day 3-4: Intent方式を削除
- Day 5: 最終動作確認

---

## リスク管理

### リスク1: 聞き返し後、ユーザーが答えない
**対策**: 3秒待って応答がなければ、もう一度聞き返す

### リスク2: 聞き返し後、ユーザーが別の質問をする
**対策**: Phaseに関係なく、別の質問として処理する

### リスク3: 割り込みのタイミングがずれる
**対策**: テンプレート内に0.5秒の間を入れる

---

## 成功基準

### フェーズ1の成功基準
- すべてのテストがPASS
- "料金教えて" → 聞き返し → "月額" → 正しい応答
- 誤案内が0件

### 全体の成功基準
- Intent方式を完全に削除できる
- コード行数が50%削減
- テストカバレッジ90%以上

