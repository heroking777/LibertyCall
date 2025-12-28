# LibertyCall システム全体説明書（統合版）

> **目的**: AIアシスタント（ChatGPT/Gemini/Cursor等）がシステム全体を瞬時に理解するための包括的な説明文。  
> このファイルは `/opt/libertycall/SYSTEM_OVERVIEW.md` と統合され、現状のディレクトリ構成・運用手順に合わせて更新されています。

---

## 📋 目次（抜粋）

1. システム概要
2. アーキテクチャ
3. 主要コンポーネント
4. システム起動方法
5. データフロー
6. 会話フロー管理
7. 技術スタック
8. 設定とカスタマイズ
9. 運用とセキュリティ
10. ポート使用状況
11. 重要な設計原則
12. 関連ドキュメント

---

## システム概要（要約）

**LibertyCall** は FreeSWITCH と連携する電話自動応対システムです。通話の RTP を受けて ASR → 会話フロー判定 → TTS を経て応答を返すリアルタイムゲートウェイと、管理用の Console Backend / Frontend、メール送信やプロジェクト管理の補助サービスで構成されています。  
現状はルールベース主体（Phase 1）で、想定外は即ハンドオフする安全設計です。

---

## アーキテクチャ（概要）

### システム構成図（ASCII）
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

---

## ディレクトリ構造（主要部分）
```
/opt/libertycall/
├── gateway_event_listener.py
├── asr_handler.py
├── google_stream_asr.py
├── gateway/
│   ├── realtime_gateway.py
│   ├── audio_manager.py
│   ├── asr_controller.py
│   ├── intent_rules.py
│   └── utils/
│       └── client_config_loader.py
├── libertycall/
│   ├── client_loader.py
│   ├── console_bridge.py
│   ├── gateway/
│   │   ├── ai_core.py
│   │   ├── flow_engine.py
│   │   ├── audio_utils.py
│   │   ├── intent_rules.py
│   │   └── transcript_normalizer.py
│   └── asr/
│       ├── __init__.py
│       └── whisper_local.py
├── console_backend/
├── frontend/
├── email_sender/
├── scripts/
├── config/
└── docs/
```

---

## 主要コンポーネント（詳細）

### 1. Gateway Event Listener (`gateway_event_listener.py`)
**責務**:
- FreeSWITCH Event Socket に接続し、通話イベント（CHANNEL_CREATE 等）を監視
- 通話開始時に `realtime_gateway.py` を起動し、RTPポート情報を渡す

### 2. Gateway (`gateway/realtime_gateway.py`)
**責務**:
- RTP (u-law 8k) 受信、u-law→PCM16k 変換、RMSベースのVAD、発話区間検出
- `ai_core.process_dialogue()` 呼び出しによる意図判定・応答生成のトリガー
- FreeSWITCH と UUID / RTP 情報のマッピング処理（`/tmp/rtp_info_*.txt`, `fs_cli` 利用）
- ASR ハンドラや WebSocket/AIOHTTP 経由の連携

#### ASR Controller API (`asr_controller.py`)
- FastAPI（ポート8000）で `/asr/start/{uuid}` を受け、`AICore.enable_asr(uuid)` を呼ぶ

### 3. AI Core (`libertycall/gateway/ai_core.py`)
**責務**:
- Google Streaming ASR 管理（`GoogleASR`）
- ルールベースの意図判定（6分類）とテンプレート選択
- Google TTS による wav 生成（非ストリーミング）
- 会話フロー管理（`FlowEngine`）への委譲と session state 管理
- クライアント別の flow/keywords/templates のホットリロード

### 4. Flow Engine (`flow_engine.py`)
**責務**:
- `flow.json` に基づく phase 遷移ロジック実行・テンプレート選択

### 5. Client Mapper / Intent Rules / Client Loader
- `client_mapper.py`: 発信者番号等から `client_id` 自動判定
- `intent_rules.py`: テキスト正規化と 6分類インテント判定
- `client_loader.py`: 設定の唯一の入口（クライアント設定読み込み）

### 6. Console Backend / Frontend
- Console Backend: FastAPI（8001）で通話ログ・ファイルログ・WebSocket を提供
- Frontend: React + Vite（5173）で管理画面を提供

### 7. Email Sender
- SendGrid を使用した自動メール送信（APScheduler ベース）、本番は systemd 管理

---

## データフロー（通話シーケンス）
1. FreeSWITCH → Gateway (RTP)
2. Gateway: デコード・VAD → ASR ストリームへ送信
3. ASR 結果 → AICore (on_transcript) → FlowEngine でフェーズ判定
4. AICore が TTS を生成 → Gateway 経由で FreeSWITCH に RTP で返却 または転送
5. ログと ASR 評価は `logs/` へ保存

---

## 会話フロー（簡易）
```
ENTRY → ENTRY_CONFIRM → QA → AFTER_085 → CLOSING → HANDOFF → HANDOFF_CONFIRM_WAIT → HANDOFF_DONE → END
```
セッションは `session_states[call_id]` で管理され、`phase`, `last_intent`, `handoff_state` 等を保持。

---

## 技術スタック（要点）
- Python 3.11+, FastAPI, asyncio, SQLAlchemy, websockets
- React 18, Vite, Tailwind
- FreeSWITCH, Nginx, systemd
- Google Cloud Speech-to-Text / Text-to-Speech

---

## 環境変数（主要）
| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `LC_ASR_PROVIDER` | ASRプロバイダ（`google` / `whisper`） | `google` |
| `LC_ASR_STREAMING_ENABLED` | ASRストリーミング有効化 | `1` |
| `LC_TTS_STREAMING` | TTSストリーミング（非対応） | `0` |
| `LC_GOOGLE_PROJECT_ID` | Google Cloud プロジェクトID | `libertycall-main` |
| `LC_GOOGLE_CREDENTIALS_PATH` | Google認証キーパス | `/opt/libertycall/key/google_tts.json` |
| `LC_RTP_PORT` | RTP受信ポート | `7002` |

---

## 運用・監視（抜粋）
- systemd 管理 (`libertycall.service`)、`START_SERVERS.sh` による起動補助
- 監視スクリプト: `monitor_asr_errors.sh`, `monitor_call.sh`, `check_rtp_alive.sh`
- ログ: `logs/conversation_trace.log`, `logs/calls/{client_id}/*.log`, `logs/asr_eval_results.json`

---

## ポート使用状況（本番想定）
| ポート | サービス |
|--------|----------|
| 80 / 443 | Nginx |
| 8000 | Gateway ASR Controller (FastAPI) |
| 8001 | Console Backend (FastAPI) |
| 3000 | Project State API (Node.js) |
| 7002 | Gateway RTP 受信 |
| 8021 | FreeSWITCH Event Socket |

---

## 重要な設計原則（抜粋）
- 設定の唯一の入口は `client_loader.py`
- 想定外発話は担当者へ転送する安全方針
- TTS は非ストリーミング（`LC_TTS_STREAMING=0` 前提）

---

## デリバリノート（別の AI に渡す時のポイント）
- 解析順: `gateway/realtime_gateway.py` → `libertycall/gateway/ai_core.py` → `asr_handler.py`
- 環境依存: `fs_cli`, `/tmp/rtp_info_*.txt`, Google 認証ファイル（モック推奨）
- ログレベルを DEBUG に上げると内部処理が追跡しやすい

---

## 関連ドキュメント
- `/opt/libertycall/QUICK_START.md`  
- `/opt/libertycall/TROUBLESHOOTING.md`  
- `/opt/libertycall/docs/project_tree.txt`  
- `/opt/libertycall/AICORE_SPEC.md`  
- `/opt/libertycall/ASR_TTS_SYSTEM_SPEC.md`

---

## 更新履歴
- 2025-12-05: 初版  
- 2025-12-20: FlowEditor・会話フロー分離追記  
- 2025-12-26: docs 全面更新（email_sender, scripts, tests 反映）  

---

このファイルは `/opt/libertycall/SYSTEM_OVERVIEW.md` と内容を統合した最新版です。さらに完全な再帰ツリー・関数一覧・PlantUML図等の自動生成を希望する場合は指示してください。


