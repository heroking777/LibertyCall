# LibertyCall システム全体説明書（完全版）

> **目的**: 本ドキュメントは LibertyCall の現行構成・運用・開発フローを網羅した「Source of Truth」です。
> `/opt/libertycall` 以下の全コンポーネントを把握し、即座に運用・保守・拡張ができるレベルの記述を目指しています。

---

## 📋 目次

1. [システム概要](#システム概要)
2. [重要ポイント（必読）](#重要ポイント)
3. [アーキテクチャ（概観）](#アーキテクチャ)
4. [ディレクトリ構造](#ディレクトリ構造)
5. [主要コンポーネント詳細](#主要コンポーネント詳細)
6. [データフロー](#データフロー)
7. [会話フロー管理（新旧）](#会話フロー管理)
8. [技術スタック](#技術スタック)
9. [環境変数一覧](#環境変数一覧)
10. [運用・デバッグ手順](#運用デバッグ手順)
11. [デプロイ・セキュリティ](#デプロイセキュリティ)
12. [トラブルシューティング](#トラブルシューティング)

---

## <a name="システム概要"></a>1. システム概要（要約）

**LibertyCall** は FreeSWITCH と連携する次世代の電話自動応対システムです。
RTP 音声ストリームをリアルタイムで受け取り、ASR (Google/Whisper) → 会話判定 (DialogueFlow/FlowEngine) → TTS (Google) を経て、自然な応答を返します。

現状は**ルールベース（Phase 1）**を基本とし、想定外の発話や複雑な要求は即座に担当者へハンドオフ（転送）する「安全第一」の設計を採用しています。

---

## <a name="重要ポイント"></a>2. 重要ポイント（必読）

- **優先解析ファイル**:
  1. `gateway/realtime_gateway.py` (音声処理の核)
  2. `libertycall/gateway/ai_core.py` (会話制御の核)
  3. `libertycall/gateway/dialogue_flow.py` (最新の判定ロジック)
- **判定方式の変更**: 従来の `intent_rules.py` (インテント方式) は廃止され、現在は `dialogue_flow.py` (フロー方式) への移行が完了しています。
- **プロセスモデル**: 各通話（UUID）ごとに独立した `realtime_gateway.py` プロセスが起動されます。
- **環境依存**: `fs_cli`、`/tmp/rtp_info_*.txt`、Google 認証 JSON は実機環境に依存します。

---

## <a name="アーキテクチャ"></a>3. アーキテクチャ（概観）

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (443/80)                          │
│  libcall.com (LP/API) / console.libcall.com (管理)           │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┬─────────────────┐
        │                 │                 │                 │
        ▼                 ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Frontend    │  │  Console      │  │  Project      │  │  Email       │
│  (React/Vite)│  │  Backend (8001)│  │  State (3000) │  │  Sender      │
│  管理画面UI   │  │  (FastAPI)   │  │  (Node.js)    │  │  (SendGrid)  │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              FreeSWITCH (PBX)                               │
│  SIP着信 → RTPストリーム (7002) → Realtime Gateway           │
│  Event Socket (8021) → Gateway Event Listener               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Gateway Event Listener                         │
│  CHANNEL_CREATE等を監視 → 各通話ごとに Gateway を Popen 起動    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Realtime Gateway (独立プロセス)                  │
│  RTP受信 → VAD → ASR → AI Core → TTS → RTP送信             │
│  (WebSocket: 9001 で管理画面への音声レベル・ログ連携)           │
└─────────────────────────────────────────────────────────────┘
```

---

## <a name="ディレクトリ構造"></a>4. ディレクトリ構造（主要部分）

```
/opt/libertycall/
├── gateway_event_listener.py   # FreeSWITCH監視・Gateway起動
├── asr_handler.py             # ASR制御のラッパー
├── google_stream_asr.py       # Google Streaming ASR実装
├── gateway/
│   ├── realtime_gateway.py    # 通話音声処理（核）
│   ├── audio_manager.py       # wav再生・管理
│   ├── asr_controller.py      # ASR起動制御API
│   └── intent_rules.py        # 旧インテント定義 (Legacy)
├── libertycall/
│   ├── client_loader.py       # クライアント設定読み込み
│   ├── console_bridge.py      # 管理コンソール連携API
│   └── gateway/
│       ├── ai_core.py         # 会話ステート・フロー管理（核）
│       ├── flow_engine.py     # flow.json に基づく遷移
│       ├── dialogue_flow.py   # 新・会話フロー判定ロジック
│       ├── audio_utils.py     # フォーマット変換(PCM/u-law)
│       ├── text_utils.py      # テキスト正規化
│       └── transcript_normalizer.py
├── console_backend/           # ポート8001, FastAPI
├── frontend/                  # React, Vite (Production: build/)
├── email_sender/              # 送信・SendGrid連携
├── project_states.json        # プロジェクト状態DB（JSON）
└── logs/                      # conversation_trace.log 等
```

---

## <a name="主要コンポーネント詳細"></a>5. 主要コンポーネント詳細

### 1) Gateway Event Listener (`gateway_event_listener.py`)
- **役割**: FreeSWITCH の Event Socket (8021) に常時接続し、通話イベントを監視。
- **動作**: `CHANNEL_PARK` や `CHANNEL_EXECUTE` (playback) をトリガーに、その通話専用の `realtime_gateway.py` プロセスを起動します。
- **サービス**: `libertycall.service` (systemd) で管理。

### 2) Realtime Gateway (`gateway/realtime_gateway.py`)
- **役割**: 1通話1プロセスの音声ゲートウェイ。
- **音声**: RTP (μ-law 8k) 受信 → PCM16k 変換 → VAD (RMSベース) → ASR転送。
- **連携**: WebSocket (9001) を通じて `console_bridge` 経由でフロントエンドへリアルタイムに音声レベルやログを流します。

### 3) AI Core (`libertycall/gateway/ai_core.py`)
- **役割**: ASR からのテキストを受け取り、`DialogueFlow` または `FlowEngine` を用いて応答を生成。
- **TTS**: Google Text-to-Speech (Neural2-B等) を使用し、非ストリーミングで wav を生成して Gateway に再生を依頼。

### 4) Project State API (Node.js)
- **役割**: `project_states.json` を管理する API。ポート3000。
- **サービス**: `libertycall-project-state-backend.service`

### 5) Console Backend & Frontend
- **Backend**: ポート8001。通話ログ、会話トレース、リアルタイム監視を提供。
- **Frontend**: React。本番環境では `console.libcall.com` 下で Nginx により配信。

---

## <a name="データフロー"></a>6. データフロー（通話シーケンス）

1. **着信**: FreeSWITCH が SIP 受信 → `gateway_event_listener` が検知。
2. **起動**: `gateway_event_listener` が `realtime_gateway.py --uuid {UUID}` を起動。
3. **ストリーム**: FreeSWITCH が RTP を 7002 ポートへ送信。Gateway が受信・VAD 処理。
4. **認識**: 発話区間を Google ASR に転送 → 認識テキストを `AICore` へ。
5. **判定**: `AICore` が `DialogueFlow` で意図・フェーズを判定 → 応答テンプレート選択。
6. **応答**: Google TTS で音声生成 → Gateway が RTP で FreeSWITCH へ返却。
7. **ログ**: `logs/` への書き込みと同時に、`console_bridge` 経由で管理画面へ送信。

---

## <a name="会話フロー管理"></a>7. 会話フロー管理（新旧）

- **フロー方式 (DialogueFlow - 最新)**:
  - 自然な会話を重視。「聞き返し」や「曖昧判定」が可能。
  - `libertycall/gateway/dialogue_flow.py` にロジックを集約。
- **インテント方式 (IntentRules - 旧)**:
  - 6つの定型インテントに分類。
  - `gateway/intent_rules.py` に依存（現在はフェーズアウト中）。

---

## <a name="技術スタック"></a>8. 技術スタック

- **言語**: Python 3.11+, Node.js (v20+)
- **フレームワーク**: FastAPI (Backend), React + Vite (Frontend)
- **音声エンジン**: Google Cloud Speech-to-Text / Text-to-Speech
- **インフラ**: FreeSWITCH (PBX), Nginx (Proxy), systemd (Service Manager)
- **DB/保存**: JSON (States), SQLAlchemy (Backend Logs), local logs

---

## <a name="環境変数一覧"></a>9. 環境変数一覧（主要）

| 変数名 | 説明 | 例 / デフォルト |
| :--- | :--- | :--- |
| `LC_ASR_PROVIDER` | ASRの種類 | `google` / `whisper` |
| `LC_RTP_PORT` | Gateway受信ポート | `7002` |
| `LC_GOOGLE_CREDENTIALS_PATH` | Google認証JSON | `/opt/libertycall/key/google_tts.json` |
| `LIBERTYCALL_CONSOLE_API_BASE_URL` | Console API URL | `https://console.libcall.com` |
| `LC_ASR_STREAMING_ENABLED` | ASRストリーミング | `1` |

---

## <a name="運用デバッグ手順"></a>10. 運用・デバッグ手順

- **サービス管理**:
  ```bash
  sudo systemctl restart libertycall.service  # Event Listener
  sudo systemctl restart libertycall-project-state-backend.service
  ```
- **リアルタイムログ確認**:
  ```bash
  tail -f /opt/libertycall/logs/conversation_trace.log
  tail -f /tmp/event_listener.log
  ```
- **RTP 到達確認**:
  ```bash
  tcpdump -nn -s0 -A udp port 7002
  ```
- **診断レポート**:
  ルートディレクトリにある `ASR_TEST_REPORT.md` や `RTP_AUDIO_FINAL_REPORT.md` を参照することで、過去の不具合と修正経緯を確認できます。

---

## <a name="デプロイセキュリティ"></a>11. デプロイ・セキュリティ

- **Nginx**:
  - `console.libcall.com`: Basic 認証 (`/etc/nginx/.htpasswd`) により保護。
  - SSL: Certbot (Let's Encrypt) による TLS 1.2/1.3 通信。
- **アクセス制御**: `.env` や `.git` などの隠しファイルは Nginx レベルでアクセス拒否設定済み。
- **バックアップ**: `tar` を用いた定期的な `config/`, `clients/`, `key/` の保存を推奨。

---

## <a name="トラブルシューティング"></a>12. トラブルシューティング（FAQ）

- **Q: 音声が全く届かない**
  - A: `ss -lunp | grep 7002` で Gateway が LISTEN しているか、`fs_cli` で `uuid_getvar {UUID} remote_media_port` が 7002 を返しているか確認。
- **Q: ASR の反応が遅い**
  - A: `LC_ASR_CHUNK_MS` (デフォルト 100-200ms) や `LC_ASR_SILENCE_MS` (発話終了判定) を調整。
- **Q: 特定のワードに反応しない**
  - A: `dialogue_flow.py` または `intent_rules.py` のキーワードリストを更新してホットリロード（プロセス再起動）。

---

*最終更新日: 2025-12-29*
*作成者: AI Assistant (LibertyCall Developer Team)*
