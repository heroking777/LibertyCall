# LibertyCall システム全体説明書

> **目的**: AIアシスタント（ChatGPT/Gemini/Cursor等）がシステム全体を瞬時に理解するための包括的な説明文

---

## 📋 目次

1. [システム概要](#システム概要)
2. [アーキテクチャ](#アーキテクチャ)
3. [主要コンポーネント](#主要コンポーネント)
4. [データフロー](#データフロー)
5. [会話フロー管理](#会話フロー管理)
6. [技術スタック](#技術スタック)
7. [設定とカスタマイズ](#設定とカスタマイズ)
8. [運用とセキュリティ](#運用とセキュリティ)
9. [ポート使用状況](#ポート使用状況)

---

## システム概要

### プロダクト名
**LibertyCall** - AIを活用した電話自動応対システム

### 現在のフェーズ
**Phase 1 – ルールベース if 分岐型 AI電話**

### 基本方針
- **24時間365日自動対応**で一次受付から要件確認まで自動処理
- **自由会話・LLM対話は非対応**（誤案内・クレーム防止のため）
- **想定されたフレーズ・パターンのみを扱う**
- **想定外の発話はすべて「担当者に繋ぐ」側に寄せる**
- 想定外が見つかれば、ルール・台本を後から追加する運用

### 主要機能

1. **AI電話自動応対**
   - FreeSWITCH（PBX）と連携したリアルタイム音声処理
   - ASR（音声認識）: Google Cloud Speech-to-Text（本番使用）
   - TTS（音声合成）: Google Cloud Text-to-Speech（非ストリーミング）
   - ルールベースの意図判定（6分類固定）
   - 会話フロー管理（ENTRY → QA → AFTER_085 → CLOSING → HANDOFF → END）
   - 自動ハンドオフ（担当者への転送）

2. **管理画面（Web Console）**
   - 通話ログの閲覧・検索（クライアントID、日付、通話IDでフィルタリング）
   - タイムライン形式での通話詳細表示
   - 統計情報・ダッシュボード
   - WebSocketによるリアルタイム更新
   - 音声テストダッシュボード（ASR/WER可視化）

3. **プロジェクト状態管理API**
   - 案件ごとの長期記憶管理
   - タスク・決定事項・問題点・重要ファイルの記録
   - カスタムGPT/MCPとの連携

4. **メール自動送信**
   - SendGridを使用した自動メール送信（本番環境）
   - 初回メール + フォローアップ3回を自動送信
   - 配信停止機能


---

## アーキテクチャ

### システム構成図

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (443/80)                          │
│  libcall.com / console.libcall.com / api.libcall.com       │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Frontend    │  │  FastAPI     │  │  Node.js     │
│  (React)     │  │  (8001)      │  │  (3000)      │
│  管理画面UI   │  │  通話ログAPI  │  │  プロジェクト │
│              │  │              │  │  状態管理API  │
└──────────────┘  └──────────────┘  └──────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              FreeSWITCH (PBX)                               │
│  SIP着信 → RTP音声ストリーム → Gateway                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Gateway (リアルタイム音声処理)                    │
│  RTP受信 → VAD → ASR → Intent判定 → TTS → RTP送信          │
│  └─→ AI Core (会話フロー管理・テンプレート選択)                │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Google ASR  │  │  Google TTS  │  │  転送判定     │
│  (音声認識)   │  │  (音声合成)   │  │  (担当者へ)   │
└──────────────┘  └──────────────┘  └──────────────┘
```

### ディレクトリ構造（主要部分）

```
/opt/libertycall/
├── gateway_event_listener.py        # FreeSWITCHイベントリスナー（通話検知・Gateway起動）
├── gateway/                          # リアルタイム音声処理
│   ├── realtime_gateway.py          # RTP受信・送信・VAD・AI呼び出し
│   ├── audio_manager.py             # 音声管理（バッファリング・チャンク処理）
│   └── intent_rules.py              # インテント判定ルール（固定6分類）
│
├── libertycall/                      # コア機能
│   ├── client_loader.py             # クライアント設定ローダー（唯一の設定入口）
│   ├── console_bridge.py            # コンソールバックエンド連携
│   └── gateway/
│       ├── ai_core.py               # AIコア（ASR→Intent→TTS統合処理・会話フロー管理）
│       ├── audio_utils.py           # 音声変換ユーティリティ（u-law⇄PCM・RMS計算）
│       ├── intent_rules.py          # インテント判定ルール（テンプレートID選択）
│       ├── transcript_normalizer.py # トランスクリプト正規化
│       └── client_mapper.py         # クライアントID自動判定（発信者番号・宛先番号・SIPヘッダー）
│
├── console_backend/                  # 管理画面API
│   ├── routers/                     # APIルーター（FastAPI）
│   │   ├── auth.py                  # 認証API
│   │   ├── calls.py                 # 通話API
│   │   ├── dashboard.py             # ダッシュボードAPI
│   │   ├── audio_tests.py           # 音声テストAPI
│   │   └── flow.py                  # 会話フロー管理API（FlowEditor用）
│   └── services/                    # ビジネスロジック層
│
├── frontend/                         # 管理画面UI（React）
│   └── src/
│       ├── pages/                   # ページコンポーネント
│       │   ├── FileLogsList.jsx     # 通話ログ一覧
│       │   ├── FileLogDetail.jsx    # 通話ログ詳細
│       │   ├── AudioTestDashboard.jsx # 音声テストダッシュボード
│       │   └── FlowEditor.jsx       # 会話フロー編集画面
│       └── components/              # UIコンポーネント
│
├── clients/                          # クライアント設定
│   ├── _TEMPLATE/                   # 新規クライアント作成用テンプレート
│   └── {client_id}/                 # クライアントID（電話番号）
│       ├── config/                  # 設定ファイル
│       │   ├── incoming_sequence.json
│       │   └── voice_lines_{id}.json
│       ├── audio/                   # クライアント専用音声ファイル
│       └── logs/                    # クライアント専用ログ
│
├── config/                           # 設定ファイル
│   ├── gateway.yaml                 # Gateway設定（ポート・クライアント）
│   ├── client_mapping.json          # クライアントID自動判定ルール
│   ├── clients/                     # クライアント別会話フロー設定
│   │   └── {client_id}/
│   │       ├── flow.json            # 会話フロー定義（phase遷移・テンプレート）
│   │       ├── keywords.json        # キーワード定義（インテント判定用）
│   │       └── templates.json       # テンプレート定義（応答メッセージ）
│   └── system/                      # システムデフォルト設定
│       ├── default_flow.json        # デフォルト会話フロー
│       ├── default_keywords.json    # デフォルトキーワード
│       └── default_templates.json   # デフォルトテンプレート
│
├── key/                              # 認証キー
│   └── google_tts.json              # Google TTS認証キー
│
├── tools/                            # ユーティリティツール
│   ├── check_rtp_alive.sh           # RTP監視スクリプト（5分ごとに実行）
│   └── validate_flow.py             # 会話フロー検証ツール（JSON構文チェック）
│
├── logs/                             # ログファイル
│   ├── calls/                       # 通話ログ
│   ├── conversation_trace.log      # 会話トレースログ
│   └── asr_eval_results.json        # ASR評価結果
│
└── src/                              # プロジェクト状態管理API（TypeScript）
    └── index.ts                     # エントリーポイント（Expressサーバー）
```

---

## 主要コンポーネント

### 1. Gateway Event Listener (gateway_event_listener.py)

**責務**:
- FreeSWITCH Event Socket に接続
- 通話イベント（CHANNEL_CREATE, CHANNEL_ANSWER, CHANNEL_EXECUTE, CHANNEL_PARK, CHANNEL_HANGUP）を監視
- 通話開始時に `realtime_gateway.py` を起動
- RTPポート情報を取得して Gateway に渡す
- systemd サービスとして常時稼働（`libertycall.service`）

### 2. Gateway (realtime_gateway.py)

**責務**:
- RTP (u-law 8kHz) 受信
- u-law → PCM16k 変換
- RMSベース発話検知（VAD）
- 発話終了判定
- バージイン（割り込み）で TTS の停止
- `ai_core.process_dialogue()` 呼び出し
- TTS音声 (PCM24k) → u-law8k 変換
- FreeSWITCH へ RTP 送信
- 転送フラグ True のとき、転送指示を ARI に送信
- クライアントID自動判定（`client_mapper.resolve_client_id()`）

**絶対にやらないこと**:
- ASR内部処理
- TTS生成
- 意図判定
→ すべて `ai_core.py` に委譲

### 3. AI Core (ai_core.py)

**責務**:
- Google Streaming ASR の管理
- テキストをルールで判定（完全ルールベース）
- 返答すべき固定メッセージを決定
- Google TTS（非ストリーミング）で wav を生成
- 会話フロー管理（phase 遷移）
- ハンドオフ判定と転送フラグ設定
- クライアント別会話フロー・キーワード・テンプレートの動的読み込み
- 会話フローのホットリロード（`reload_flow()`）

**会話フロー管理**:
- `session_states[call_id]` で各通話の状態を管理
- phase: `ENTRY` → `ENTRY_CONFIRM` → `QA` → `AFTER_085` → `CLOSING` → `HANDOFF` → `HANDOFF_CONFIRM_WAIT` → `HANDOFF_DONE` → `END`
- 各種フラグ: `last_intent`, `handoff_state`, `transfer_requested` など
- クライアント別設定: `/config/clients/{client_id}/flow.json`, `keywords.json`, `templates.json`
- デフォルト設定: `/config/system/default_*.json`（クライアント別設定がない場合のフォールバック）

### 4. Client Mapper (client_mapper.py)

**責務**:
- 発信者番号・宛先番号・SIPヘッダーから `client_id` を自動判定
- `config/client_mapping.json` のルールに基づいて判定
- デフォルトは `client_id="000"`

### 5. Intent Rules (intent_rules.py)

**責務**:
- テキスト正規化（全角・半角統一・記号除去）
- インテント分類（6分類固定）:
  1. `SALES_CALL` - 営業電話
  2. `INQUIRY` - 問い合わせ
  3. `HANDOFF_REQUEST` - 転送要求
  4. `END_CALL` - 通話終了
  5. `NOT_HEARD` - 聞き取れない
  6. `UNKNOWN` - 不明
- テンプレートID選択（応答メッセージの決定）

### 6. Console Backend (console_backend/)

**責務**:
- 通話ログの CRUD 操作
- ユーザー管理・認証
- 統計情報の集計
- WebSocket によるリアルタイム更新
- 音声テスト結果の管理

**技術スタック**:
- FastAPI
- SQLAlchemy (SQLite)
- WebSocket

### 7. Frontend (frontend/)

**責務**:
- 通話ログ一覧・詳細表示
- ダッシュボード（統計情報・グラフ）
- 音声テストダッシュボード（ASR/WER可視化）
- WebSocket によるリアルタイム更新

**技術スタック**:
- React 18
- Vite
- Tailwind CSS
- Recharts（グラフ表示）

### 8. Client Loader (client_loader.py)

**責務**:
- **設定の唯一の入口**（他のコンポーネントは直接設定ファイルを読まない）
- `client_id`（電話番号）を受け取る
- `/clients/{id}/config.json` と `rules.json` を読む
- greeting音声のパスを絶対パスに変換
- `{config, rules, path情報}` を dict で返す

**禁止事項**:
- `realtime_gateway.py` で設定を直接読む行為
- 設定ファイルを直接 `open()` する行為

---

## データフロー

### 通話処理フロー

1. **着信**
   - ユーザーが 050 番号に発信
   - FreeSWITCH が SIP を受け、`rtp_stream` で Gateway に RTP を転送

2. **音声受信・処理**
   - `realtime_gateway.py` が RTP u-law(8k) を受信
   - PCM16k に変換（音声処理用）
   - フレームごとに RMS を計算し、発話区間を検出（VAD）
   - 音声チャンクを **Google Streaming ASR** に流す

3. **AI処理**
   - 最終認識結果を **AICore** に渡す
   - AICore が以下を実行:
     - テキスト正規化
     - インテント分類
     - 会話フロー判定（phase 遷移）
     - テンプレートID選択
     - Google TTS（非ストリーミング）で wav を生成

4. **音声送信**
   - AICore から返ってきた TTS 音声（wav）を u-law(8k) に変換
   - RTP で FreeSWITCH に送り返す

5. **転送判定**
   - 転送フラグが立っていれば、人間の担当者に転送
   - ARI 経由で転送実行

### ログ記録フロー

1. **会話トレースログ** (`logs/conversation_trace.log`)
   - フェーズ・テンプレートID・発話内容を記録
   - 会話フローの検証・デバッグに使用

2. **通話ログ** (`logs/calls/{client_id}/*.log`)
   - クライアントごとの通話ログ
   - Console Backend で管理画面に表示

3. **ASR評価結果** (`logs/asr_eval_results.json`)
   - WER（Word Error Rate）計算結果
   - Webダッシュボードで可視化

---

## 会話フロー管理

### Phase（フェーズ）一覧

| Phase | 説明 |
|-------|------|
| `ENTRY` | 初期フェーズ。最初の発話を待つ |
| `ENTRY_CONFIRM` | ENTRY で ENTRY_TRIGGER_KEYWORDS が検出された場合の確認フェーズ |
| `QA` | 通常の質問応答フェーズ |
| `AFTER_085` | SALES_CALL や通常の応答後に遷移するフェーズ |
| `CLOSING` | クロージングフェーズ。YES 系応答で HANDOFF へ、NO 系応答で END へ |
| `HANDOFF` | ハンドオフ開始フェーズ（060/061/062/104 を返す） |
| `HANDOFF_CONFIRM_WAIT` | ハンドオフ確認待ちフェーズ（0604 を返した後、ユーザーの YES/NO を待つ） |
| `HANDOFF_DONE` | ハンドオフ完了フェーズ（081/082 を返した後、転送実行済み） |
| `END` | 会話終了フェーズ。自動切断タイマー（60秒）がセットされる |

### 状態遷移図（簡易版）

```
ENTRY → QA → AFTER_085 → CLOSING → HANDOFF → HANDOFF_CONFIRM_WAIT → HANDOFF_DONE → END
  │       │       │          │         │              │                    │
  │       │       │          │         │              │                    │
  └───────┴───────┴──────────┴─────────┴──────────────┴────────────────────┘
          │                                                                    │
          └────────────────────────────────────────────────────────────────────┘
```

詳細な状態遷移条件は `AICORE_SPEC.md` を参照。

### Session State（セッション状態）

各通話は `session_states[call_id]` で以下の情報を管理:

- `phase`: 現在のフェーズ
- `last_intent`: 前回のユーザー発話の intent
- `handoff_state`: ハンドオフの状態（`idle` / `confirming` / `done`）
- `handoff_retry_count`: ハンドオフ確認の再提示回数
- `transfer_requested`: 転送リクエストが発行されたか
- `not_heard_streak`: 「もう一度お願いします」の連続回数
- `unclear_streak`: AI がよくわからない状態で返答した回数
- その他、メタ情報など

---

## 技術スタック

### バックエンド
- **Python 3.11+**
  - FastAPI（管理画面API）
  - SQLAlchemy（データベースORM）
  - asyncio（非同期処理）
  - websockets（WebSocket通信）

### フロントエンド
- **React 18**
- **Vite**（ビルドツール）
- **Tailwind CSS**（スタイリング）
- **Recharts**（グラフ表示）

### 音声処理
- **Google Cloud Speech-to-Text**（本番使用）
  - StreamingRecognize (v1p1beta1)
  - 16kHz / PCM16 / mono
- **Google Cloud Text-to-Speech**（非ストリーミング）
  - 24kHz / PCM24 → u-law 8kHz に変換

### インフラ
- **FreeSWITCH**（PBX）
  - Dialplan設定: `/usr/local/freeswitch/conf/dialplan/`
  - 段階的アナウンス: `sleep` + `transfer`（タイマー制御）
  - 音声ファイル: 8kHz μ-law形式（PCMU/8000）
- **Nginx**（リバースプロキシ）
- **systemd**（サービス管理）
- **SQLite**（通話ログ）
- **JSON**（プロジェクト状態）

### その他
- **Node.js/Express**（プロジェクト状態管理API）
- **SendGrid**（メール送信）

---

## 設定とカスタマイズ

### クライアント設定

各クライアントは `/clients/{client_id}/` ディレクトリに以下を配置:

1. **config.json**
   - forward先（転送先電話番号）
   - 店名
   - 音声定義

2. **rules.json**（旧形式、非推奨）
   - intentルール／キーワード
   - テンプレートID選択ルール

3. **audio/** ディレクトリ
   - クライアント専用音声ファイル（.wav）

### クライアント別会話フロー設定（新形式）

各クライアントは `/config/clients/{client_id}/` ディレクトリに以下を配置:

1. **flow.json**
   - 会話フロー定義（phase遷移・テンプレートID・条件分岐）
   - バージョン管理（`version`, `updated_at`）

2. **keywords.json**
   - キーワード定義（インテント判定用）
   - `ENTRY_TRIGGER_KEYWORDS`, `CLOSING_YES_KEYWORDS`, `CLOSING_NO_KEYWORDS` など

3. **templates.json**
   - テンプレート定義（応答メッセージ）
   - テンプレートIDとテキストのマッピング

**デフォルト設定**: `/config/system/default_*.json`（クライアント別設定がない場合のフォールバック）

**クライアントID自動判定**: `config/client_mapping.json` のルールに基づいて、発信者番号・宛先番号・SIPヘッダーから自動判定

### 環境変数（主要）

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `LC_ASR_PROVIDER` | ASRプロバイダ（`google` / `whisper`） | `google` |
| `LC_ASR_STREAMING_ENABLED` | ASRストリーミング有効化 | `1` |
| `LC_TTS_STREAMING` | TTSストリーミング（**非対応、0固定**） | `0` |
| `LC_GOOGLE_PROJECT_ID` | Google Cloud プロジェクトID | `libertycall-main` |
| `LC_GOOGLE_CREDENTIALS_PATH` | Google認証キーパス | `/opt/libertycall/key/google_tts.json` |
| `LC_RTP_PORT` | RTP受信ポート | `7002` |
| `LC_GATEWAY_PORT` | Gatewayポート（旧） | - |

### Gateway設定

`config/gateway.yaml`:
- RTPポート設定
- クライアント設定

---

## 運用とセキュリティ

### セキュリティ
- Nginx Basic認証（管理画面・API）
- SSL/TLS（Let's Encrypt）
- 個人情報は保持せず、その場で処理のみ
- 想定外の内容は全て担当者へ即転送する安全設計

### 運用
- 24時間365日自動対応
- 通話ログの自動記録・保存
- ログ分析による応答精度の継続的改善
- クライアントごとの応答ルール・音声のカスタマイズ対応
- systemd サービス管理（`libertycall.service`）
- ログローテーション（`/etc/logrotate.d/libertycall`）
- RTP監視・自動再起動（`check_rtp_alive.timer`）

### 監視・ログ
- 会話トレースログ（`logs/conversation_trace.log`）
- 通話ログ（`logs/calls/{client_id}/*.log`）
- ASR評価結果（`logs/asr_eval_results.json`）
- Gatewayログ（`/tmp/gateway_*.log`）
- Event Listenerログ（`/tmp/event_listener.log`）
- RTP監視ログ（`/tmp/check_rtp_alive.log`）

### テスト・検証
- 会話フロー統合テスト（`scripts/test_flow_integration.sh`）
- 音声フロー統合テスト（`scripts/test_audio_flow.sh`）
- 自動リグレッションテスト（`scripts/test_regression_audio.sh`）
- 全体連携検証（`scripts/verify_integration.sh`）

---

## ポート使用状況

### 本番環境で使用中のポート

| ポート | サービス | 用途 |
|--------|----------|------|
| 80 | Nginx | HTTP（HTTPSへのリダイレクト用） |
| 443 | Nginx | HTTPS（SSL/TLS） |
| 8000 | （未使用） | - |
| 8001 | FastAPI | 管理画面API |
| 3000 | Node.js/Express | プロジェクト状態管理API |
| 7002 | Gateway | RTP受信ポート |
| 9001 | Gateway | WebSocket接続（AI処理連携） |
| 5173 | Vite | 開発用（フロントエンド） |

### ポート変更時の注意事項

⚠️ **重要**: ポート番号を変更する前に、必ず `/opt/libertycall/docs/project_tree.txt` の「ポート使用状況一覧」セクション（504行目以降）を確認してください。

- 既存のポートと競合すると、システムが停止する可能性があります
- ポート変更後は、この一覧を更新してください（追記のみ、上書き禁止）
- 古いポート情報は「（旧）」などのマークを付けて残してください

---

## 重要な設計原則

### 1. 責務分離
- **設定変更** → `clients/{id}/config.json`
- **ルール変更** → `clients/{id}/rules.json`
- **音声変換** → `audio_utils`
- **意図判定** → `ai_core / rules`
- **通信ロジック** → `realtime_gateway`
- **ARI制御** → `liberty_rt`

### 2. 設定の唯一の入口
- `client_loader.py` が設定を読み込む唯一の入口
- 他のコンポーネントは直接設定ファイルを読まない

### 3. 安全設計
- 想定外の発話はすべて「担当者に繋ぐ」側に寄せる
- ASR エラー時は即座に担当者へ転送
- 自由会話・LLM対話は非対応（誤案内防止）

### 4. TTS は非ストリーミング
- `LC_TTS_STREAMING=0` 前提のコードを壊さない
- Google TTS は非ストリーミングで使用

### 5. ASR プロバイダ変更は大工事扱い
- Whisper / 他社 ASR などへの切り替えは、勝手にやらない

---

## 関連ドキュメント

- **プロジェクト構造**: `/opt/libertycall/docs/project_tree.txt`
- **AIコア仕様**: `/opt/libertycall/AICORE_SPEC.md`
- **ASR/TTS仕様**: `/opt/libertycall/ASR_TTS_SYSTEM_SPEC.md`
- **会話フロー**: `/opt/libertycall/docs/会話フロー一覧.md`（存在する場合）
- **クイックスタート**: `/opt/libertycall/QUICK_START.md`
- **トラブルシューティング**: `/opt/libertycall/TROUBLESHOOTING.md`

---

## 更新履歴

- 2025-12-05: 初版作成
- 2025-12-20: クライアント単位会話フロー分離・FlowEditor・運用安定タスクを追加

---

**このドキュメントは、AIアシスタントが LibertyCall システムを理解するための包括的な説明文です。**
**システムの変更に応じて、定期的に更新してください。**

