# LibertyCall システム全体説明書

> **目的**: AIアシスタント（ChatGPT/Gemini/Cursor等）がシステム全体を瞬時に理解するための包括的な説明文

---

## 📋 目次

1. [システム概要](#システム概要)
2. [アーキテクチャ](#アーキテクチャ)
3. [主要コンポーネント](#主要コンポーネント)
4. [システム起動方法](#システム起動方法)
5. [データフロー](#データフロー)
6. [会話フロー管理](#会話フロー管理)
7. [技術スタック](#技術スタック)
8. [設定とカスタマイズ](#設定とカスタマイズ)
9. [運用とセキュリティ](#運用とセキュリティ)
10. [ポート使用状況](#ポート使用状況)
11. [重要な設計原則](#重要な設計原則)
12. [関連ドキュメント](#関連ドキュメント)

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
   - APSchedulerによる定期実行（毎日指定時刻）
   - CSVファイルによる送信先リスト管理
   - 配信停止機能（SendGrid Webhook連携）
   - バウンスメール自動削除


---

## アーキテクチャ

### システム構成図

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (443/80)                          │
│  libcall.com / console.libcall.com / api.libcall.com       │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┬─────────────────┐
        │                 │                 │                 │
        ▼                 ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Frontend    │  │  FastAPI     │  │  Node.js     │  │  Email       │
│  (React)     │  │  (8001)      │  │  (3000)      │  │  Sender      │
│  管理画面UI   │  │  通話ログAPI  │  │  プロジェクト │  │  (SendGrid)  │
│  (5173)      │  │              │  │  状態管理API  │  │              │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              FreeSWITCH (PBX)                               │
│  SIP着信 → RTP音声ストリーム → Gateway                      │
│  Event Socket (8021) → Gateway Event Listener               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Gateway Event Listener                         │
│  通話イベント監視 → Gateway起動                              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Gateway (リアルタイム音声処理)                    │
│  RTP受信 → VAD → ASR → Intent判定 → TTS → RTP送信          │
│  └─→ AI Core (会話フロー管理・テンプレート選択)                │
│  └─→ ASR Controller API (8000)                             │
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
├── asr_handler.py                   # ASRハンドラー（旧実装、参考用）
├── google_stream_asr.py             # Google Streaming ASR（旧実装、参考用）
│
├── gateway/                          # リアルタイム音声処理
│   ├── realtime_gateway.py          # RTP受信・送信・VAD・AI呼び出し
│   ├── audio_manager.py             # 音声管理（バッファリング・チャンク処理）
│   ├── asr_controller.py             # ASR Controller API（FastAPI、ポート8000）
│   ├── intent_rules.py              # インテント判定ルール（固定6分類、旧実装）
│   └── utils/                        # ユーティリティ
│       └── client_config_loader.py  # クライアント設定ローダー（Gateway用）
│
├── libertycall/                      # コア機能
│   ├── client_loader.py             # クライアント設定ローダー（唯一の設定入口）
│   ├── console_bridge.py            # コンソールバックエンド連携
│   ├── gateway/
│   │   ├── ai_core.py               # AIコア（ASR→Intent→TTS統合処理・会話フロー管理）
│   │   ├── flow_engine.py           # 会話フローエンジン（phase遷移管理）
│   │   ├── audio_utils.py           # 音声変換ユーティリティ（u-law⇄PCM・RMS計算）
│   │   ├── intent_rules.py          # インテント判定ルール（テンプレートID選択）
│   │   ├── transcript_normalizer.py # トランスクリプト正規化
│   │   └── client_mapper.py         # クライアントID自動判定（発信者番号・宛先番号・SIPヘッダー）
│   └── asr/                          # ASRプロバイダ実装
│       ├── __init__.py              # ASRプロバイダファクトリー
│       └── whisper_local.py         # WhisperローカルASR（開発用）
│
├── console_backend/                  # 管理画面API（FastAPI）
│   ├── main.py                      # FastAPIエントリーポイント
│   ├── config.py                    # 設定管理
│   ├── database.py                   # データベース接続（SQLAlchemy）
│   ├── models.py                    # データモデル定義
│   ├── schemas.py                    # Pydanticスキーマ定義
│   ├── routers/                     # APIルーター
│   │   ├── calls.py                 # 通話API（ログ取得・イベント記録）
│   │   ├── logs.py                  # ログAPI（ファイルログ読み取り）
│   │   ├── audio_tests.py           # 音声テストAPI（ASR評価結果）
│   │   ├── flow.py                  # 会話フロー管理API（FlowEditor用・ホットリロード）
│   │   └── sendgrid_webhook.py      # SendGrid Webhook（配信停止処理）
│   ├── services/                    # ビジネスロジック層
│   │   ├── call_service.py          # 通話サービス
│   │   └── file_log_service.py      # ファイルログサービス
│   ├── websocket/                    # WebSocket実装
│   │   ├── dispatcher.py            # イベントディスパッチャー
│   │   └── routes.py                # WebSocketルート
│   └── migrations/                   # データベースマイグレーション（Alembic）
│
├── frontend/                         # 管理画面UI（React + Vite）
│   ├── src/
│   │   ├── main.jsx                 # エントリーポイント
│   │   ├── App.jsx                  # ルートコンポーネント
│   │   ├── config.js                # 設定（APIエンドポイント等）
│   │   ├── pages/                   # ページコンポーネント
│   │   │   ├── FileLogsList.jsx     # 通話ログ一覧
│   │   │   ├── FileLogDetail.jsx     # 通話ログ詳細（タイムライン表示）
│   │   │   ├── AudioTestDashboard.jsx # 音声テストダッシュボード（ASR/WER可視化）
│   │   │   └── FlowEditor.jsx       # 会話フロー編集画面
│   │   └── components/              # UIコンポーネント
│   │       ├── ConsoleLayout.jsx    # レイアウトコンポーネント
│   │       └── ConsoleHeader.jsx    # ヘッダーコンポーネント
│   ├── package.json                 # 依存関係（React 18, Vite, Tailwind CSS, Recharts）
│   └── vite.config.js               # Vite設定
│
├── email_sender/                     # メール自動送信システム
│   ├── main.py                      # メインエントリーポイント
│   ├── config.py                    # 設定管理
│   ├── sendgrid_client.py           # SendGridクライアント（本番使用）
│   ├── ses_client.py                # AWS SESクライアント（旧実装）
│   ├── scheduler_service_prod.py    # 本番スケジューラー（APScheduler）
│   ├── scheduler_service.py          # 開発用スケジューラー
│   ├── csv_repository_prod.py       # 本番CSVリポジトリ
│   ├── csv_repository.py            # 開発用CSVリポジトリ
│   ├── models.py                    # データモデル
│   ├── data/                        # データファイル
│   │   └── master_leads.csv         # 送信先リスト（本番）
│   ├── list/                        # 送信先リスト（開発用）
│   ├── templates/                   # メールテンプレート
│   ├── clean_master_leads.py        # マスターリストクリーンアップ
│   ├── remove_bounced_emails.py     # バウンスメール削除
│   └── README.md                    # メール送信システム説明書
│
├── scripts/                          # ユーティリティスクリプト
│   ├── asr_eval.py                  # ASR評価（WER計算）
│   ├── test_audio_asr.py            # 音声ASRテスト
│   ├── generate_*.py                # 音声生成スクリプト（TTS）
│   │   ├── generate_gemini_tts.py   # Gemini TTS生成
│   │   ├── generate_f5_tts.py       # F5 TTS生成
│   │   └── generate_voicevox_tts.py # VoiceVox TTS生成
│   ├── check_*.py                   # チェックスクリプト
│   │   ├── check_audio_files.py     # 音声ファイルチェック
│   │   ├── check_google_apis.py    # Google API接続チェック
│   │   └── check_dependencies.py    # 依存関係チェック
│   ├── monitor_*.sh                 # 監視スクリプト
│   │   ├── monitor_call.sh          # 通話監視
│   │   └── monitor_asr_test.sh      # ASRテスト監視
│   ├── test_*.py                    # テストスクリプト
│   ├── verify_*.sh                  # 検証スクリプト
│   ├── sync_*.py                    # 同期スクリプト
│   └── handoff_*.py                 # ハンドオフ関連スクリプト
│
├── tests/                            # テストコード
│   ├── conftest.py                  # pytest設定
│   ├── test_console_backend.py      # コンソールバックエンドテスト
│   ├── test_ai_core_handoff.py      # AIコアハンドオフテスト
│   ├── test_initial_sequence.py    # 初期シーケンステスト
│   ├── test_generate_initial_greeting.py # 初期挨拶生成テスト
│   ├── test_misunderstanding_guard.py  # 誤解防止ガードテスト
│   └── test_production_performance.py   # 本番パフォーマンステスト
│
├── freeswitch/                       # FreeSWITCH Dialplan設定
│   ├── README.md                    # FreeSWITCH Dialplan説明書
│   ├── dialplan/                    # Dialplan設定ファイル
│   │   ├── default.xml              # 段階アナウンス（sleep+transfer）設定
│   │   └── public.xml               # 外線経由の入口（FORCE_PUBLICエントリ）
│   └── audio/                       # 8kHz音声ファイル
│       ├── 000_8k.wav               # 初期アナウンス音声
│       ├── 001_8k.wav               # 初期アナウンス音声
│       ├── 002_8k.wav               # 初期アナウンス音声
│       ├── 000-004_8k.wav           # 段階アナウンス音声
│       ├── 000-005_8k.wav           # 段階アナウンス音声
│       ├── 000-006_8k.wav           # 段階アナウンス音声
│       └── combined_intro_8k.wav    # 000+001+002統合ファイル
│
├── clients/                          # クライアント設定
│   ├── _TEMPLATE/                   # 新規クライアント作成用テンプレート
│   │   └── config/
│   │       └── incoming_sequence.json
│   ├── 000/                         # クライアント000
│   │   ├── config/
│   │   │   ├── incoming_sequence.json
│   │   │   └── voice_lines_000.json
│   │   ├── audio/                   # クライアント専用音声ファイル
│   │   └── logs/                    # クライアント専用ログ
│   └── {client_id}/                 # その他のクライアント
│
├── config/                           # 設定ファイル
│   ├── gateway.yaml                 # Gateway設定（ポート・クライアント）
│   ├── client_mapping.json          # クライアントID自動判定ルール
│   ├── google-credentials.json      # Google認証情報（本番用）
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
├── key/                              # 認証キー（旧形式、参考用）
│   └── google_tts.json              # Google TTS認証キー（旧）
│
├── tools/                            # ユーティリティツール
│   ├── check_rtp_alive.sh           # RTP監視スクリプト（5分ごとに実行）
│   ├── check_rtp_traffic.sh         # RTPトラフィック監視
│   ├── check_process_and_logs.sh   # プロセス・ログチェック
│   ├── monitor_gateway_live.sh     # Gatewayライブ監視
│   ├── diagnose_intro_template.sh   # イントロテンプレート診断
│   └── validate_flow.py             # 会話フロー検証ツール（JSON構文チェック）
│
├── logs/                             # ログファイル
│   ├── calls/                       # 通話ログ（クライアント別）
│   │   └── {client_id}/
│   ├── conversation_trace.log       # 会話トレースログ
│   └── asr_eval_results.json        # ASR評価結果
│
├── src/                              # プロジェクト状態管理API（TypeScript/Express）
│   ├── index.ts                     # エントリーポイント（Expressサーバー、ポート3000）
│   └── README_STRUCTURE_AUTO_SYNC.md # 構造自動同期説明書
│
├── libs/                             # 外部ライブラリ
│   └── esl/                         # FreeSWITCH ESL（Event Socket Library）
│       └── ESL.py                   # PyESL実装
│
├── deploy/                           # デプロイ関連
│   └── systemd/                     # systemdサービス定義
│       └── README.md                # systemd設定説明書
│
├── lp/                               # ランディングページ関連
│   ├── contact_api.py               # お問い合わせAPI
│   └── scripts/                     # LP用スクリプト
│
├── alembic/                          # データベースマイグレーション
│   ├── alembic.ini                  # Alembic設定
│   └── versions/                    # マイグレーションファイル
│
├── requirements.txt                  # Python依存関係
├── package.json                     # Node.js依存関係（プロジェクト状態管理API）
├── tsconfig.json                     # TypeScript設定
├── openapi.yaml                      # OpenAPI定義（プロジェクト状態管理API用）
├── README.md                         # プロジェクト説明書
├── QUICK_START.md                    # クイックスタートガイド
├── TROUBLESHOOTING.md                # トラブルシューティングガイド
├── START_SERVERS.sh                  # サーバー起動スクリプト
└── Makefile                           # Makefile（開発用コマンド）
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

**ASR Controller API (asr_controller.py)**:
- FastAPIサーバー（ポート8000）をバックグラウンドで起動
- `/asr/start/{uuid}` エンドポイントでFreeSWITCHからのASR起動通知を受信
- `AICore.enable_asr(uuid)` を呼び出してGoogleASRストリーミングを開始

**絶対にやらないこと**:
- ASR内部処理
- TTS生成
- 意図判定
→ すべて `ai_core.py` に委譲

### 3. AI Core (ai_core.py)

**責務**:
- Google Streaming ASR の管理（`GoogleASR` クラス）
- テキストをルールで判定（完全ルールベース）
- 返答すべき固定メッセージを決定
- Google TTS（非ストリーミング）で wav を生成
- 会話フロー管理（phase 遷移）を `FlowEngine` に委譲
- ハンドオフ判定と転送フラグ設定
- クライアント別会話フロー・キーワード・テンプレートの動的読み込み
- 会話フローのホットリロード（`reload_flow()`）

**会話フロー管理**:
- `session_states[call_id]` で各通話の状態を管理
- `FlowEngine` を使用して phase 遷移を管理
- phase: `ENTRY` → `ENTRY_CONFIRM` → `QA` → `AFTER_085` → `CLOSING` → `HANDOFF` → `HANDOFF_CONFIRM_WAIT` → `HANDOFF_DONE` → `END`
- 各種フラグ: `last_intent`, `handoff_state`, `transfer_requested` など
- クライアント別設定: `/config/clients/{client_id}/flow.json`, `keywords.json`, `templates.json`
- デフォルト設定: `/config/system/default_*.json`（クライアント別設定がない場合のフォールバック）

### 3-1. Flow Engine (flow_engine.py)

**責務**:
- 会話フローの phase 遷移ロジックを管理
- `flow.json` の定義に基づいて phase 遷移を実行
- テンプレートID選択ロジック
- 条件分岐処理（キーワードマッチング等）
- `AICore` から呼び出されて使用される

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
- 通話ログの CRUD 操作（`calls.py`）
- ファイルログの読み取り（`logs.py`）
- 統計情報の集計
- WebSocket によるリアルタイム更新（`websocket/dispatcher.py`）
- 音声テスト結果の管理（`audio_tests.py`）
- 会話フローのホットリロード（`flow.py`）
- SendGrid Webhook処理（`sendgrid_webhook.py`）

**主要APIエンドポイント**:
- `GET /api/logs` - 通話ログ一覧取得
- `GET /api/logs/{call_id}` - 通話ログ詳細取得
- `GET /api/calls` - 通話履歴取得
- `POST /api/calls/events` - 通話イベント記録
- `GET /api/audio-tests/latest` - 最新ASR評価結果
- `POST /api/flow/reload` - 会話フローホットリロード
- `WS /ws/calls` - WebSocket（リアルタイム更新）

**技術スタック**:
- FastAPI
- SQLAlchemy (SQLite)
- WebSocket
- Alembic（データベースマイグレーション）

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

### 9. Email Sender (email_sender/)

**責務**:
- SendGridを使用した自動メール送信（本番環境）
- 初回メール + フォローアップ3回を自動送信
- APSchedulerによる定期実行（`scheduler_service_prod.py`）
- CSVファイルによる送信先リスト管理（`master_leads.csv`）
- 配信停止機能（SendGrid Webhook連携）
- バウンスメール自動削除（`remove_bounced_emails.py`）

**主要ファイル**:
- `main.py` - メインエントリーポイント
- `sendgrid_client.py` - SendGrid APIクライアント
- `scheduler_service_prod.py` - 本番スケジューラー
- `csv_repository_prod.py` - 本番CSVリポジトリ

### 10. プロジェクト状態管理API (src/)

**責務**:
- 案件ごとの長期記憶管理（`project_states.json`）
- タスク・決定事項・問題点・重要ファイルの記録
- カスタムGPT/MCPとの連携（OpenAPI定義: `openapi.yaml`）
- プロジェクト構造の自動同期（`watch_project_tree.py`）

**主要エンドポイント**:
- `GET /projects` - 案件一覧取得
- `GET /projects/:projectId/state` - 案件状態取得
- `POST /projects/:projectId/state` - 案件状態保存
- `POST /projects/:projectId/logs` - ログ追記
- `GET /health` - ヘルスチェック

**技術スタック**:
- Node.js/Express
- TypeScript
- JSONファイルベース（将来SQLite移行予定）

---

## システム起動方法

### 1. Gateway Event Listener（必須）

```bash
# systemdサービスとして起動（推奨）
sudo systemctl start libertycall.service
sudo systemctl enable libertycall.service

# または手動起動
cd /opt/libertycall
python3 gateway_event_listener.py
```

**役割**: FreeSWITCHの通話イベントを監視し、通話開始時にGatewayを起動

### 2. Console Backend（管理画面API）

```bash
cd /opt/libertycall
uvicorn console_backend.main:app --reload --host 0.0.0.0 --port 8001
```

**役割**: 管理画面のAPIサーバー（通話ログ・統計情報等）

### 3. Frontend（管理画面UI）

```bash
cd /opt/libertycall/frontend
npm install  # 初回のみ
npm run dev  # 開発サーバー起動（ポート5173）
```

**役割**: 管理画面のWeb UI

### 4. プロジェクト状態管理API（オプション）

```bash
cd /opt/libertycall
npm install  # 初回のみ
npm run dev  # 開発サーバー起動（ポート3000）
```

**役割**: カスタムGPT/MCPとの連携用API

### 5. メール送信システム（オプション）

```bash
cd /opt/libertycall
source venv/bin/activate
python3 email_sender/main.py
```

**役割**: 自動メール送信（本番環境ではsystemdサービスとして起動）

### 一括起動スクリプト

```bash
cd /opt/libertycall
./START_SERVERS.sh  # Console Backend + Frontend を起動
```

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
- **Node.js/Express**（プロジェクト状態管理API、ポート3000）
- **SendGrid**（メール送信、本番環境）
- **AWS SES**（メール送信、旧実装・参考用）
- **APScheduler**（メール送信スケジューラー）
- **Alembic**（データベースマイグレーション）
- **pytest**（テストフレームワーク）

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

### メール送信設定

**SendGrid設定** (`email_sender/config.py`):
- SendGrid API Key（環境変数 `SENDGRID_API_KEY`）
- 送信者メールアドレス（環境変数 `SENDER_EMAIL`）
- 送信上限（環境変数 `DAILY_SEND_LIMIT`、デフォルト: 100）
- フォローアップ間隔（環境変数 `FOLLOWUP1_DAYS_AFTER` 等）

**送信先リスト**:
- 本番: `email_sender/data/master_leads.csv`
- 開発: `email_sender/list/recipients.csv`

**スケジュール設定**:
- 送信時刻: 環境変数 `EMAIL_SEND_HOUR`（デフォルト: 9時）
- APSchedulerで定期実行

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
- **pytestテストスイート** (`tests/`)
  - `test_console_backend.py` - コンソールバックエンドテスト
  - `test_ai_core_handoff.py` - AIコアハンドオフテスト
  - `test_initial_sequence.py` - 初期シーケンステスト
  - `test_generate_initial_greeting.py` - 初期挨拶生成テスト
  - `test_misunderstanding_guard.py` - 誤解防止ガードテスト
  - `test_production_performance.py` - 本番パフォーマンステスト
- **統合テストスクリプト** (`scripts/`)
  - `verify_integration.sh` - 全体連携検証
  - `test_audio_asr.py` - 音声ASRテスト
  - `asr_eval.py` - ASR評価（WER計算）

---

## ポート使用状況

### 本番環境で使用中のポート

| ポート | サービス | 用途 |
|--------|----------|------|
| 80 | Nginx | HTTP（HTTPSへのリダイレクト用） |
| 443 | Nginx | HTTPS（SSL/TLS） |
| 8000 | Gateway ASR Controller | FreeSWITCHからのASR起動通知受信（FastAPI） |
| 8001 | FastAPI | 管理画面API（Console Backend） |
| 3000 | Node.js/Express | プロジェクト状態管理API |
| 7002 | Gateway | RTP受信ポート |
| 9001 | Gateway | WebSocket接続（AI処理連携、旧実装） |
| 5173 | Vite | 開発用（フロントエンド） |
| 8021 | FreeSWITCH | Event Socket（gateway_event_listener.py接続） |

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

### システム全体
- **このドキュメント**: `/opt/libertycall/docs/SYSTEM_OVERVIEW.md`（システム全体説明書）
- **クイックスタート**: `/opt/libertycall/QUICK_START.md`（管理画面起動手順）
- **トラブルシューティング**: `/opt/libertycall/TROUBLESHOOTING.md`（トラブル解決ガイド）
- **プロジェクト構造**: `/opt/libertycall/docs/project_tree.txt`（詳細なディレクトリ構造）

### 機能別ドキュメント
- **AIコア仕様**: `/opt/libertycall/AICORE_SPEC.md`（会話フロー管理の詳細仕様）
- **ASR/TTS仕様**: `/opt/libertycall/ASR_TTS_SYSTEM_SPEC.md`（音声処理の詳細仕様）
- **SendGrid認証チェックリスト**: `/opt/libertycall/docs/SENDGRID_AUTH_CHECKLIST.md`（メール送信設定ガイド）

### コンポーネント別ドキュメント
- **FreeSWITCH Dialplan**: `/opt/libertycall/freeswitch/README.md`（Dialplan設定説明）
- **Console Backend**: `/opt/libertycall/console_backend/README.md`（API仕様）
- **Frontend**: `/opt/libertycall/frontend/README.md`（UI開発ガイド）
- **Email Sender**: `/opt/libertycall/email_sender/README.md`（メール送信システム説明）
- **プロジェクト状態管理API**: `/opt/libertycall/README.md`（カスタムGPT連携ガイド）

### スクリプト・ツール
- **Gemini TTS**: `/opt/libertycall/scripts/README_gemini_tts.md`（Gemini TTS生成ガイド）
- **RTP検出**: `/opt/libertycall/scripts/README_RTP_DETECTION.md`（RTP検出スクリプト説明）
- **プロジェクト構造同期**: `/opt/libertycall/scripts/README_SYNC_PROJECT_STRUCTURE.md`（構造同期ツール説明）
- **ASRテストコマンド**: `/opt/libertycall/scripts/ASR_TEST_COMMANDS.md`（ASRテスト手順）

---

## 更新履歴

- 2025-12-05: 初版作成
- 2025-12-20: クライアント単位会話フロー分離・FlowEditor・運用安定タスクを追加
- 2025-12-26: 最新のファイル構成に合わせて全面更新（email_sender、scripts、tests、Flow Engine等を追加）

---

**このドキュメントは、AIアシスタントが LibertyCall システムを理解するための包括的な説明文です。**
**システムの変更に応じて、定期的に更新してください。**

