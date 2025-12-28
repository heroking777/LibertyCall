# LibertyCall システム全体説明書（完全版）

> **目的**: 本ドキュメントは「このファイルを読めば LibertyCall の現行構成・運用・トラブルシュート・開発フローが理解できる」ことを目標に作成しています。  
> `/opt/libertycall` 以下のソース／設定／運用手順を一元的にまとめ、別のエンジニアや AI に渡して即運用・解析できるレベルの記述を意識しています。

---

## 目次（抜粋）

1. システム概要
2. 重要ポイント（必読）
3. アーキテクチャ
4. 主要コンポーネント
5. データフロー
6. 会話フロー管理
7. 技術スタック
8. 前提・インストール
9. 環境変数一覧
10. 運用チェックリスト・デバッグ手順
11. テスト・デプロイ手順
12. トラブルシューティング（FAQ）
13. バックアップ/復元
14. 関連ドキュメント
15. 更新履歴

---

## システム概要（要約）

**LibertyCall** は FreeSWITCH と連携する電話自動応対システムです。RTP を受け取り ASR → 会話フロー判定 → TTS で応答を返すリアルタイムゲートウェイを核とし、管理用 Console Backend / Frontend、メール送信、プロジェクト状態管理API 等が補助的に連携します。  
現状はルールベース（Phase 1）を基本とし、想定外の発話は担当者へハンドオフする安全方針を採っています。

---

## 重要ポイント（まずこれを確認）
- このファイルを「source of truth」として運用してください。重要な環境変数・ポート・起動手順はここを更新すること。  
- 優先解析ファイル（解析順）:
  1. `gateway/realtime_gateway.py`  
  2. `libertycall/gateway/ai_core.py`  
  3. `asr_handler.py`  
  4. `gateway/asr_controller.py`（FastAPI: `/asr/start`）  
- テスト実行時は `fs_cli` 呼び出しや `/tmp/rtp_info_*.txt` の読み取りをモックしてください（これらは実機依存）。

---

## アーキテクチャ（概観）
（省略可能な ASCII 図は下記を参照）
```
Nginx (443/80)
  ├─ Frontend (React/Vite)
  ├─ Console Backend (FastAPI, 8001)
  └─ Project State API (Node.js, 3000)
FreeSWITCH (PBX) -- Event Socket (8021) --> Gateway Event Listener --> Gateway (realtime_gateway.py)
Gateway --> ASR/TTS (Google等) / AICore --> Response → FreeSWITCH
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

## 主要コンポーネント（要点と運用メモ）

### 1) Gateway Event Listener (`gateway_event_listener.py`)
責務:
- FreeSWITCH の Event Socket に接続し、通話イベント（CHANNEL_CREATE 等）を監視
- 通話開始時に Gateway を起動（RTP ポート情報を渡す）

運用メモ:
- systemd での自動起動を想定。起動失敗時は `/tmp/event_listener.log` を確認。

### 2) Gateway (`gateway/realtime_gateway.py`)
責務:
- RTP (μ-law 8k) 受信 → PCM16k 変換 → VAD（RMS ベース）→ ASR へストリーム転送
- ASR の中間/最終結果を `AICore` に流し、応答 (TTS) を生成して FreeSWITCH に返す
- FreeSWITCH 側の UUID と通話 ID のマッピング（`/tmp/rtp_info_*.txt`、`fs_cli` の出力解析）

運用チェック:
- `LC_RTP_PORT` と `LC_GATEWAY_PORT` の競合に注意。`ss -lunp` で確認。  
- RTP が来ているかはログの `[RTP_RECV_RAW]` を確認。受信がなければネットワーク/FreeSWITCH 側を確認。

#### ASR Controller (`gateway/asr_controller.py`)
- FastAPI（ポート8000）で `/asr/start/{uuid}` を受け、`AICore.enable_asr(uuid)` を呼び出す。FreeSWITCH 側はこのエンドポイントを通じて ASR の開始/停止を制御。

### 3) AI Core (`libertycall/gateway/ai_core.py`)
責務:
- Google Streaming ASR 管理（`GoogleASR` クラス）・ASR からの partial を受け取って会話状態に反映
- ルールベースのインテント判定（6分類）とテンプレート選択、FlowEngine を用いたフェーズ管理
- Google TTS（非ストリーミング）で wav を生成、TTS を Gateway 経由で再生

運用メモ:
- Google 認証ファイルは `GOOGLE_APPLICATION_CREDENTIALS` / `LC_GOOGLE_CREDENTIALS_PATH` で指定。実行ユーザーの権限を確認。  
- `GoogleASR` はスレッド+キューで動くため、キュー詰まりやワーカースレッド停止をログで監視。

### 4) Flow Engine (`libertycall/gateway/flow_engine.py`)
責務:
- `flow.json` の定義に従い phase 遷移・テンプレート選択を行う。AICore から呼ばれて使用される。

### 5) Client Mapper / Client Loader / Intent Rules
- `client_mapper.py`: 発信者番号・宛先番号・SIP ヘッダから `client_id` を判定（`config/client_mapping.json`）  
- `client_loader.py`: クライアント設定の唯一の入口（各コンポーネントは直接設定を読まない）  
- `intent_rules.py`: テキスト正規化と 6分類インテント判定

### 6) Console Backend / Frontend
- Console Backend: FastAPI（8001）で通話ログ、会話トレース、ファイルログを API として提供。WebSocket によりリアルタイム更新を行う。  
- Frontend: React + Vite（開発: 5173）で管理画面を提供。デプロイはビルド済みファイルを Nginx 配下に置く運用が基本。

### 7) Email Sender
- SendGrid ベースの自動メール送信（APScheduler でスケジュール実行）。本番は systemd 管理を想定。

---

## データフロー（通話シーケンス）
1. FreeSWITCH が SIP 着信 → RTP を Gateway に転送  
2. Gateway が RTP を受信、デコード → VAD により発話区間を検出 → 音声チャンクを ASR に送出  
3. ASR の結果（partial/final）を AICore に渡す（`on_transcript`）  
4. AICore が FlowEngine によりフェーズ判定 → テンプレート選択 → 必要なら外部 API 呼び出し  
5. TTS を生成し、Gateway 経由で FreeSWITCH に RTP またはファイル再生で返却／転送  
6. 通話ログ・会話トレース・ASR 評価は `logs/` に保存。Console Backend で参照可能。

---

## 会話フロー（簡易）
```
ENTRY → ENTRY_CONFIRM → QA → AFTER_085 → CLOSING → HANDOFF → HANDOFF_CONFIRM_WAIT → HANDOFF_DONE → END
```
各通話は `session_states[call_id]` により `phase`, `last_intent`, `handoff_state`, `not_heard_streak` 等を管理します。詳細は `AICORE_SPEC.md` を参照してください。

---

## 技術スタック（要点）
- Python 3.11+（FastAPI, asyncio, SQLAlchemy, websockets）  
- React 18 / Vite / Tailwind（Frontend）  
- FreeSWITCH（PBX）、Nginx（TLS / リバースプロキシ）、systemd（サービス管理）  
- Google Cloud Speech-to-Text / Text-to-Speech（本番利用）  
- Node.js / Express（Project State API）

---

## 前提（インストール / 必要ソフトウェア）
- OS: Linux（Debian/Ubuntu 系での動作確認）  
- Python 3.11+, pip, virtualenv  
- Node.js, npm（frontend / src）  
- FreeSWITCH（fs_cli が利用可能）  
- Google Cloud サービスアカウント JSON（ASR/TTS 利用時）

インストールの最小例:
```bash
python3 -m venv /opt/libertycall/venv
source /opt/libertycall/venv/bin/activate
pip install -r /opt/libertycall/requirements.txt
```

---

## 環境変数（主要）
| 変数名 | 説明 | デフォルト / 例 |
|--------|------|----------------|
| `LC_ASR_PROVIDER` | ASRプロバイダ（`google` / `whisper`） | `google` |
| `LC_ASR_STREAMING_ENABLED` | ASRストリーミング有効化 | `1` |
| `LC_TTS_STREAMING` | TTSストリーミング（非対応） | `0` |
| `LC_GOOGLE_PROJECT_ID` | Google Cloud プロジェクトID | `libertycall-main` |
| `LC_GOOGLE_CREDENTIALS_PATH` | Google認証キーパス | `/opt/libertycall/key/google_tts.json` |
| `LC_RTP_PORT` | RTP受信ポート | `7002` |
| `LC_GATEWAY_PORT` | Gateway 管理ポート（運用による） | 例: `7001` |

---

## 運用チェックリスト（1分で確認）
- サービス状態: `systemctl status libertycall.service`  
- Gateway プロセス確認: `ps aux | rg realtime_gateway.py`  
- ログ確認: `tail -n 200 /opt/libertycall/logs/conversation_trace.log`  
- RTP ポート確認: `ss -lunp | rg 7002`（受信プロセスが LISTEN/RECV しているか）  
- FreeSWITCH 接続確認: `fs_cli -x "show channels"` が応答するか

---

## デバッグ手順（代表例）
1) 音声が ASR に到達しない  
- Gateway ログに `[RTP_RECV_RAW]` が出ているか確認  
- ネットワークで RTP が送信されているか: `tcpdump -nn -s0 -A udp port 7002`（本番では注意）  
- `/tmp/rtp_info_*.txt` の内容（local=, uuid=）を確認

2) Google 認証エラー  
- `echo $LC_GOOGLE_CREDENTIALS_PATH` / `echo $GOOGLE_APPLICATION_CREDENTIALS` を確認  
- JSON のパーミッション: `ls -l /opt/libertycall/key/google_tts.json`

3) FreeSWITCH で通話が切れる / 音声が途切れる  
- Dialplan の rtp ポート設定と Gateway の設定整合性を確認  
- Gateway の RTP エコー設定（`RTPProtocol` 実装）を確認

---

## テスト手順
- 単体: `pytest tests/ -q`  
- 統合: テスト環境の FreeSWITCH を用意して `scripts/test_audio_asr.py` を実行  
- ASR 精度: `python scripts/asr_eval.py --gold gold.txt --hyp hyp.txt`

---

## デプロイ / リリース手順（簡易）
1. `git pull origin main` をテスト環境で動作確認  
2. 依存更新: `source venv/bin/activate && pip install -r requirements.txt`（必要時）  
3. systemd 再読み込み・再起動:
```bash
sudo systemctl daemon-reload
sudo systemctl restart libertycall.service
```
4. ロールバックは旧タグ/コミットを checkout して同様に再起動

---

## バックアップ / 復元（最低限）
- バックアップ対象: `config/`, `clients/`, `key/`, `logs/`  
```bash
tar czf /var/backups/libertycall_$(date +%F).tgz /opt/libertycall/config /opt/libertycall/clients /opt/libertycall/key /opt/libertycall/logs
```

---

## トラブルシューティング（FAQ）
- Q: `fs_cli` が見つからない / permission denied  
  - A: 実行 PATH に `fs_cli` を追加、または systemd ユニットで絶対パスを指定。`which fs_cli` で確認。  
- Q: Google 認証エラー（credentials not found）  
  - A: `LC_GOOGLE_CREDENTIALS_PATH` を環境に設定、実行ユーザーが読めるか確認。  
- Q: ASR スレッドが死んでいる（ghost thread）  
  - A: プロセスを再起動し、`GoogleASR` のログ（STREAM_WORKER）を確認。必要ならキューサイズを一時的に増やす。

---

## 関連ドキュメント（主要）
- `/opt/libertycall/QUICK_START.md`  
- `/opt/libertycall/TROUBLESHOOTING.md`  
- `/opt/libertycall/docs/project_tree.txt`（完全再帰ツリー）  
- `/opt/libertycall/AICORE_SPEC.md`  
- `/opt/libertycall/ASR_TTS_SYSTEM_SPEC.md`

---

## 連絡先 / 所有者（テンプレート）
- オーナー: `team-libertycall@example.com`  
- 運用当番: `oncall@example.com`  
- ドキュメント保守: `docs-owner@example.com`

---

## 更新履歴
- 2025-12-05: 初版  
- 2025-12-20: FlowEditor・会話フロー分離追記  
- 2025-12-26: docs 全面更新（email_sender, scripts, tests 反映）  
- 2025-12-29: 統合版を完全版に拡張（運用チェックリスト・デバッグ手順等を追加）

---

このファイルは `/opt/libertycall/SYSTEM_OVERVIEW.md` と内容を統合した最新版です。  
さらに以下を自動生成できます（希望を教えてください）: 完全再帰ツリー、ファイル別関数シグネチャ一覧、PlantUML シーケンス図。
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
