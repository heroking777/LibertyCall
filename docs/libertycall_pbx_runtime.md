---8<--- START OF FILE ---8<---
# LibertyCall PBX Runtime Memo
最終更新: 2025-11-06 JST

## 0. このファイルの目的
Asterisk/AGI/TTS/ASR まわりの**運用ルールと現状**を一元管理。  
チャットが変わってもこの1枚で再現・復旧ができる。

---

## 1. 実体ファイルと動作の要点（稼働中）
- `/etc/asterisk/extensions.d/zz_incoming_active.conf`  
   - 稼働コンテキスト: `incoming-call` / `decide` / `ahentry` / `vm`
   - 営業時間内は `[decide]`、時間外は `[ahentry]`→`[vm]`。
- `/var/lib/asterisk/agi-bin/pbx_bridge.py`  
   - 録音WAVをASR（Google STT）→ ルール判定 → 変数返却。
   - 戻り変数（Asteriskへ）：  
      - `LAST_TRANSCRIPT`（テキスト）  
      - `TRANSFER_TO`（転送先。空なら無転送）  
      - `ACTION` = `transfer` / `voicemail` / `ai`
- `/var/lib/asterisk/sounds/ja/*.ulaw`（TTSプロンプト）  
   - 例: `greeting, company_name, qm_notice, ask_plain, confirm_transfer, callback_notice`
- 録音保存: `/var/spool/asterisk/libertycall/`  
   - `msg-*.wav`（発話） / `voicemail-*.wav`（留守電）

**番号正規化（`[decide]`）**  
`CALLERID(num)`→ダメなら PAI→ダメなら From。`+81` or `81` 先頭は国内表記（090/080/070）へ→`RC_NAT` に保持。  
**営業時間**: 10:00–17:30（Mon–Fri）

---

## 2. 電話フロー（簡略）
1) `incoming-call,58304073` で案内再生→`Record(msg-*.wav)`→`AGI(pbx_bridge.py, REC_PATH)`  
2) 営業時間内: `[decide]`  
    - `ACTION="transfer"` → `confirm_transfer` → `Dial(PJSIP/${TRANSFER_TO}@rk-endpoint,45,rg)` → 不在は `[vm]`  
    - `ACTION="voicemail"` → 直ちに `[vm]`  
    - `ACTION="ai"` → いまはフォールバックで `[vm]`（将来 AI ハンドラへ）  
3) 時間外: `[ahentry]` → `[vm]`  
4) `[vm]` : `callback_notice` 再生 → `Record(voicemail-*.wav,10,60,q)` → `Hangup`

---

## 3. 現在の一次ルール（pbx_bridge.py）
- HP/お問い合わせ/資料請求 系の語+呼びかけ → `ACTION="transfer"`、`TRANSFER_TO` 設定  
- それ以外（例: 折り返しお願いしますのみ） → `ACTION="voicemail"`  
- ログ: `NoOp(Heard:${LAST_TRANSCRIPT})`、`lc_logwrite.sh` に `RC_NAT` と発話を渡す

---

## 4. ログ（messages）を使う場合
`/etc/asterisk/logger.conf`
```

[general]
dateformat=%Y-%m-%d %H:%M:%S
[logfiles]
messages => notice,warning,error,verbose
console  => notice,warning,error

```
再読込: `asterisk -rx 'logger reload'`  
監視例: `tail -F /var/log/asterisk/messages | egrep -i 'NoOp|pbx_bridge|Dial|Goto|Record|lc_logwrite'`

---

## 5. フォルダ構成（プロジェクト側・要点）
```

LibertyCall/
├─ pbx/                  # PBX制御/ラッパ等
├─ asr/                  # ASR関連（Google STTクライアント等）
├─ tts/                  # TTS関連（Google TTSクライアント等）
├─ dialog/               # 対話制御（状態管理/応答方針）
├─ deps/                 # 外部依存（pjsua_customなど）
├─ runtime/              # 実行生成物（※リポジトリ除外）
├─ deploy/               # デプロイスクリプト類（Asterisk/TTS 等）
├─ docs/                 # 本メモ等のドキュメント
└─ ...                   # その他（frontend, tools, tests など）

```
※ `.gitignore` により `.venv/`, `runtime/`, `logs/`, `*.wav`, `keys/` を除外済み。

---

## 6. 音声プロンプト運用（Google TTS）
- 音声エンジン: Google Cloud Text-to-Speech  
- Voice: `ja-JP-Neural2-B`（女性、日本語、Natural高品質）  
- 変換: 24kHz → 8kHz u-law（電話品質）  
- 出力先: `/var/lib/asterisk/sounds/ja/`  
- 代表ファイル: `greeting.ulaw / company_name.ulaw / qm_notice.ulaw / ask_plain.ulaw / confirm_transfer.ulaw / callback_notice.ulaw`  
- 生成スクリプト（例）: `/media/sf_LibertyCall/deploy/asterisk/make_prompts.sh`  
   - 再生成後は `asterisk -rx 'module reload res_musiconhold.so'` 等ではなく、**音声は直接参照**のためそのまま有効（念のため `asterisk -rx 'core reload'` 可）

---

## 7. 環境変数・設定（抜粋）
- `GOOGLE_APPLICATION_CREDENTIALS` : GCPサービスアカウントJSON  
- （運用メモ）`LC_GREETING_TEXT`, `LC_DISABLE_PJSUA_START` などはPBX側で使用（将来的に統一設定へ）

---

## 8. バックアップ運用
- Asteriskダイヤルプラン: `/etc/asterisk/extensions.d/zz_incoming_active.conf.bak.YYYYMMDD-HHMMSS`  
- AGI: `/var/lib/asterisk/agi-bin/pbx_bridge.py.bak.<timestamp>`  
- 方針: 変更前に必ずバックアップ→`dialplan reload`→即テスト→NGなら直ちに戻す

---

## 9. 再構築（Ubuntu簡易手順）
1) ダイヤルプラン確認  
```

asterisk -rx 'dialplan show incoming-call'
asterisk -rx 'dialplan show decide'
asterisk -rx 'dialplan show vm'

```
2) AGI/音声/録音パス確認  
```

ls -l /var/lib/asterisk/agi-bin/pbx_bridge.py
ls -l /var/lib/asterisk/sounds/ja/{greeting,company_name,qm_notice,ask_plain,confirm_transfer,callback_notice}.ulaw
ls -ld /var/spool/asterisk/libertycall

```
3) リロード  
```

asterisk -rx 'dialplan reload'

```

---

## 10. クライアント別ルール（将来拡張）
- DID/トランク→`LC_TENANT` 振分、`tenant.yml`（例）で `営業時間/ACTION/TRANSFER_TO` を外出し。  
- `ACTION="ai"` ルートの追加（Asterisk: `Goto(ai-handler,s,1)`、外部処理と接続）。

---

## 11. 運用ルール（GPT / Copilot / Ubuntu）
- **GPT（設計/指示）**: 変更案は必ず本.mdに追記案を提示。新規ファイルは作らず“既存に追記”。  
- **Copilot（リポ管理）**: この.mdを**唯一の真実**として更新→`git add/commit/push`。  
- **Ubuntu（実機）**: 手順は短く・分割。`dialplan reload` 後に通話で即確認。  
- 禁止事項: 推測作業・重複ファイル作成・未確認パスでの更新。

---

## 12. トラブル対処メモ
- `messages` が無い: `logger.conf` を上記にし `logger reload`。  
- `extension not found` : DID→`incoming-call` のマッピングと `58304073` エントリ確認。  
- 転送不在→留守電: `DIALSTATUS` をログで確認、`lc_logwrite.sh` の実行権限・引数を確認。

---
 (See <attachments> above for file contents. You may not need to search or read the file again.)

## 15. AI分岐設計とログ統合仕様（v2.2）

### 15.1 目的
LibertyCall の PBX は「AIで完結できる問い合わせ」と「担当転送が必要な問い合わせ」を自動で判別し、  
通話内容に応じたルートへ誘導する。  
本章ではその分岐構成とログ一元化の仕様を定義する。

### 15.2 構成概要
```

[incoming-call]
│
├─ AGI(pbx_bridge.py) → 音声認識＆分類
│        │
│        ├─ ACTION="ai"     → Goto(ai-handler,s,1)
│        ├─ TRANSFER_TO!=空 → Goto(decide,s,1)
│        └─ それ以外        → Goto(vm,s,1)

```

### 15.3 AI分岐の条件設計（pbx_bridge.py）

| フラグ | 判定内容 | ルート |
|---------|-----------|---------|
| `strong_hit` | 高確度で「電話を希望」「折り返し依頼」などが含まれる | decide（転送） |
| `intent_hit` | 一般的な連絡・資料請求ワード | decide（転送） |
| `action_ai` | 「営業時間」「アクセス」「メール」「営業時間外対応」など FAQ で処理可 | ai-handler（AI応答） |
| その他 | 無発話・不明瞭 | vm（留守電） |

※ `action_ai` 判定は正規表現ルール＋AI分類（今後 `nlu/ai_router.py` で強化予定）

### 15.4 ai-handler コンテキスト設計

```asterisk
[ai-handler]
exten => s,1,NoOp(AI mode start: Heard=${LAST_TRANSCRIPT})
 same  => n,Set(CHANNEL(language)=ja)
 same  => n,AGI(/var/lib/asterisk/agi-bin/ai_handler.py,${LAST_TRANSCRIPT})
 same  => n,Hangup()
```

* `ai_handler.py`

   * 目的：FAQ応答生成（Google TTS経由で音声返答）
   * 出力：`ja/ai_response.wav` を動的再生
   * 応答内容例：「弊社の営業時間は平日10時から17時半です。」
   * 今後の拡張：Dialogflow or Vertex AI に接続可能な構造にする。

### 15.5 ログ統合仕様

* **呼び出し元:** decide / ai-handler / vm すべて共通で `/usr/local/bin/lc_logwrite.sh` を呼ぶ。
* **形式:** `/var/log/libertycall/calllog-YYYYMMDD.jsonl` に追記。
* **拡張項目:**

   * `action_route`: `"ai"`, `"transfer"`, `"voicemail"`
   * `ai_reply`: AI応答テキスト（ai-handlerのみ）
   * `confidence`: ASR信頼度（pbx_bridge出力）

例（JSONL 1行）:

```json
{
   "ts_human": "2025/11/06/18:10",
   "caller": "09012345678",
   "transcript": "営業時間を教えてください",
   "action_route": "ai",
   "ai_reply": "弊社の営業時間は平日10時から17時半です。",
   "confidence": 0.95
}
```

### 15.6 拡張ロードマップ

| フェーズ                  | 目的                  | 概要                                              |
| --------------------- | ------------------- | ----------------------------------------------- |
| Phase A               | `ai-handler` 実装     | FAQ応答をPythonで実行（TTS音声生成含む）                      |
| Phase B               | `lc_logwrite.sh` 拡張 | JSONLに action_route / ai_reply / confidence を追加 |
| Phase C               | WebUI統合             | `/var/log/libertycall/` のJSONをReact管理画面で可視化     |
| Phase D               | CRM連携               | 顧客電話番号に紐づく履歴をAPI化（FastAPI予定）                    |
| ---8<--- END ---8<--- |                     |                                                 |


### 14. 運用固定ルール（LibertyCall専用）

本章は LibertyCall 開発・運用時の ChatGPT／Copilot／Ubuntu 間連携ポリシーを明文化する。  
手動操作ミス防止・再現性確保を目的とする。

1. **ChatGPT（GPT-5）が主導する運用方針**
   - 新しいファイル・スクリプト・設定・ドキュメントを生成した際は、  
     **必ず Copilot に貼り付け可能な「指示ブロック」** を同時に出力する。  
   - 指示ブロックは以下の情報を必ず含む：  
     - 対象ファイル名・保存パス  
     - 内容本文（新規 or 更新差分）  
     - 推奨コミットメッセージ  
     - 実行用 Git コマンド  
     - 対応する `.md` 更新指示（追記箇所）

2. **ユーザー操作の最小化**
   - ユーザー（heroking777）は Copilot に指示を貼り付けるだけでよい。  
   - ChatGPT 側から「実行していいか？」などの確認は不要。  
   - 作業の正確性・順序決定は ChatGPT 側が責任を持つ。

3. **目的**
   - 手動転記・設定漏れ・ヒューマンエラーを完全排除。  
   - Copilot／Ubuntu 双方の構成を常に同期。  
   - プロジェクト環境を誰でも再現可能な状態で維持。

4. **適用範囲**
   - 現時点では LibertyCall プロジェクト専用ルールとする。  
   - 将来新規システムを構築する際も、明示的に承認されれば同形式を再利用可。

---

sudo asterisk -rx 'logger reload'

```

ログを見るコマンド：
```

sudo tail -F /var/log/asterisk/messages | egrep -i 'NoOp|pbx_bridge|Dial|Goto|Record|lc_logwrite'

```

---

## 7. 今後の拡張予定（覚書）
- **クライアントごとのルール対応**  
  → `ACTION` の判断を pbx_bridge.py 内で切り替え可能にする。
- **`ai` アクション対応**  
  → AI応答専用ハンドラを追加し、「自動回答で完結」できる仕組みへ。
- **テナント設定ファイル**  
  → `/etc/libertycall/tenant.yml` 等で、転送先や営業時間を個別設定。

---

## 8. 更新ルール
- ChatGPT（GPT-5）は、AsteriskやAGIを変更したら必ずこの `.md` を更新案付きで提示。
- Copilotは、提示された更新案を確認し、Gitにコミット＆プッシュする。
- バックアップ命名：`zz_incoming_active.conf.bak.YYYYMMDD-HHMMSS`

---

## 9. 最終動作確認（Ubuntu VM）
```

sudo asterisk -rx 'dialplan show incoming-call'
sudo asterisk -rx 'dialplan show decide'
sudo asterisk -rx 'dialplan show vm'
ls -l /var/lib/asterisk/agi-bin/pbx_bridge.py
ls -l /var/lib/asterisk/sounds/ja/*.ulaw

```

---

