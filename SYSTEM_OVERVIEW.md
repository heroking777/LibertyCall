# LibertyCall システム全体ドキュメント

**目的**  
このドキュメントは `/opt/libertycall` にある LibertyCall プロジェクト全体を別の AI が読み取り・理解できるようにまとめたものです。アーキテクチャ、主要コンポーネント、データフロー、設定、起動手順、ログ、トラブルシューティング、主要ファイルの概要、及びプロジェクトツリーを含みます。

---

## 1. 高レベル概要（アーキテクチャ）
- 音声通話を受け取り ASR（音声認識）→ NLU/ダイアログ→ TTS/再生 までを処理するリアルタイム通話ゲートウェイ。
- 主な役割:
  - RTP/UDP パケットの受信・監視・エコー（FreeSWITCH/電話系と連携）
  - ストリーミング ASR（Google / Whisper 等）との連携
  - AICore（対話管理 / フローエンジン）による応答生成とハンドオフ管理
  - ロギング／診断・モニタリング（ASRエラー監視・RTT解析等）
- 実行形態:
  - Systemd サービスや起動スクリプト（`START_SERVERS.sh` / `systemd_example.service`）
  - 開発用は `realtime_gateway.py` の単独実行も可能

---

## 2. 主要コンポーネント一覧と説明
- `gateway/realtime_gateway.py`
  - UDP/RTP を受信するエントリポイント。RTP を解析して ASR 用に整形し、`AICore` を呼ぶ。
  - `RTPProtocol`, `RTPPacketBuilder`, `FreeswitchRTPMonitor` 等のクラスを含む。
  - FreeSWITCH との連携ロジック（uuid 取得、rtp_info ファイル参照、fs_cli 呼び出し）を持つ。
  - ASR ハンドラ（外部 `asr_handler`）や WebSocket/AIOHTTP 経由のモジュールと連携可能。
- `libertycall/gateway/ai_core.py`
  - 対話管理／AI 統合の中心部（AICore クラス群）。
  - Google ASR（`GoogleASR` クラス）、Gemini/LLM 統合、FlowEngine / dialogue_flow の呼び出しを含む。
  - ASR の結果を受けて `on_transcript` を経由し意図解析・応答生成・外部API呼び出しを行う。
  - スレッド／キュー管理、ストリーミング管理、認証ファイルパスや環境変数の扱いが記載されている。
- `libertycall/gateway/audio_utils.py`
  - サンプリング変換、u-law/PCM 変換など音声処理ユーティリティ。
- `libertycall/gateway/text_utils.py`, `transcript_normalizer.py`
  - テキスト正規化、テンプレート選択、ハンドオフ解釈など。
- `libertycall/flow_engine`, `libertycall/dialogue_flow`
  - 対話フローの実装、レスポンステンプレート、状態遷移管理。
- `asr_handler.py`
  - 複数 ASR 実装（Whisper, Google 等）切替ロジックを含むハンドラ管理。
- `console_bridge.py`
  - ロギングまたは開発コンソールへのブリッジ（デバッグ用）。
- その他:
  - `gateway_event_listener.py`（イベント受信）
  - `google_stream_asr.py`（Google ストリーミング ASR 補助スクリプト）
  - `freeswitch` ディレクトリ（FreeSWITCH 関連スクリプト・設定）
  - `config/`, `deploy/`, `scripts/`：運用・デプロイ用設定やユーティリティ

---

## 3. データフロー（通話1件の概略）
1. FreeSWITCH などから RTP を ` /opt/libertycall/gateway/realtime_gateway.py` が受信（UDP socket / asyncio Datagram）。
2. `RTPProtocol.datagram_received` → エコー処理（必要に応じ） → `handle_rtp_packet` をキック。
3. パケットが ASR に適したフォーマットに変換され、ASR ストリーム（`GoogleASR` など）へ送られる。
4. ASR の中間結果/最終結果が `AICore.on_transcript` に渡される。
5. `AICore` は `FlowEngine` / `dialogue_flow` を使って意図判定、テンプレート選択、必要なら外部 API（CRM / DB / SSO）呼び出しを行う。
6. 応答テキストは `tts`（ローカル or Google TTS 等）で音声に変換され、Freeswitch 経由で再生されるか RTP 経路で返される。
7. ログ・メトリクスは `logs/` に出力され、監視スクリプト（`monitor_asr_errors.sh` 等）で監視される。

---

## 4. 重要な環境変数・設定項目
- Google 認証:
  - `GOOGLE_APPLICATION_CREDENTIALS`（または `LC_GOOGLE_CREDENTIALS_PATH`）
  - `LC_GOOGLE_PROJECT_ID`
- ゲートウェイポート:
  - `LC_GATEWAY_PORT`（デフォルト 7000、開発用に 7001 などを利用）
- ASR/TTS の切替設定: `config/` 配下の YAML / JSON でプロバイダ指定
- FreeSWITCH 関連:
  - `/tmp/rtp_info_*.txt`（Lua スクリプト等が出力）
  - fs_cli 実行可能パス（`fs_cli` が PATH にあること）
- ログ・デバッグ:
  - 各モジュールの logger 名（例: `libertycall.gateway.ai_core`）でログレベルを変更可能

---

## 5. 起動手順（開発 / 本番）
- 開発: 環境をセット
  - 仮想環境: `python3 -m venv venv && source venv/bin/activate`
  - 依存インストール: `pip install -r requirements.txt`
  - 開発用実行（ポート上書き可）:
    - `export LC_GATEWAY_PORT=7001`
    - `./venv/bin/python libertycall/gateway/realtime_gateway.py`
- 本番（systemd サービス例）
  - `systemd_example.service` を参考にユニット作成
  - 必要な環境変数を systemd 環境に設定
  - `sudo systemctl daemon-reload && sudo systemctl enable --now libertycall.service`
- デバッグ:
  - `run_test_gateway.sh`, `test_*` スクリプトや `LOG` ディレクトリを参照
  - `console_bridge` で開発コンソールへ接続

---

## 6. ログとメトリクス
- ログ出力先: `logs/`（ファイル名やローテートは設定による）
- 重要ログメッセージ:
  - `[RTP_RECV_RAW]`：RTP 受信の記録
  - `[ASR_RES]` / `GoogleASR: ASR_GOOGLE_RAW`：ASR の部分・最終結果
  - `[FS_RTP_MONITOR]`：FreeSWITCH RTP 監視ログ
  - エラーは例外情報付きで logger.error に出力される
- 監視スクリプト:
  - `monitor_asr_errors.sh`, `monitor_call.sh` 等で定期チェック
- トラブル時のまず見る場所:
 1. systemd ジャーナル: `journalctl -u libertycall.service`
 2. `logs/` の直近ファイル
 3. ` /tmp/rtp_info_*.txt`（RTCP/RT P情報）

---

## 7. セキュリティ上の注意点
- 認証ファイル（Google サービスアカウント JSON）は適切に保護し、リポジトリにコミットしないこと。
- `fs_cli` 等を使用する外部コマンド呼び出しはタイムアウトと例外処理を必ず行う（コード内で対応済み）。
- 公開 API を作成する場合は適切な認可（APIキー / OAuth）を追加すること。

---

## 8. 主要ファイルの短いサマリ（抜粋）
- `gateway/realtime_gateway.py`：RTP受信、RTP監視、ASRへの橋渡し、FreeSWITCH連携。
- `libertycall/gateway/ai_core.py`：AICore、GoogleASR クラス、対話フロー統合、ストリーム管理。
- `asr_handler.py`：ASR ハンドラのファクトリ関数（実装の切り替えなど）。
- `config/`：サービスの設定ファイル群（YAML 等）。
- `deploy/`：デプロイ関連スクリプト・テンプレート。
- `scripts/`：ユーティリティスクリプト（診断、再起動、検査など）。
- `README.md` / `QUICK_START.md`：プロジェクト概要・起動手順（参照推奨）。

---

## 9. 運用・トラブルシューティングのチェックリスト
- 音声が聞こえない／ASRが反応しない:
  - UDP ポート（`LC_GATEWAY_PORT`）が正しいか
  - `RTP_RECV_RAW` ログの有無（realtime_gateway のログ）
  - `/tmp/rtp_info_*.txt` に port/uuid 情報があるか
- FreeSWITCH と連携できない:
  - `fs_cli` 実行が成功するか（権限、パス）
  - `uuid_dump` 出力で `variable_rtp_local_port` を確認
- Google ASR の認証エラー:
  - `GOOGLE_APPLICATION_CREDENTIALS` のパス、ファイル権限
  - `LC_GOOGLE_PROJECT_ID` 設定
- スレッド／キュー詰まり:
  - `GoogleASR` の thread/queue の状態ログを確認
  - 長時間のストリームは再起動ポリシーを確認

---

## 10. 拡張・カスタマイズ箇所（提案）
- LLM プロバイダの追加（Gemini / OpenAI）を `ai_core` にプラガブルに実装。
- ASR のフェイルオーバー（Whisper⇄Google）を設定で切替可能にする。
- Prometheus メトリクスを導入し稼働監視を自動化。
- E2E テストスイート（`tests/` を拡張）で通話シナリオを自動化。

---

## 11. リポジトリ トップレベルツリー（抜粋）
以下は `ls` で取得したトップレベルの抜粋ツリーです。サブディレクトリは代表的なもののみ列挙しています。

```
/opt/libertycall/
├─ alembic/
├─ alembic.ini
├─ ASR_ACTION_REPORT.md
├─ asr_handler.py
├─ backups/
├─ clients/
├─ config/
├─ console_backend/
├─ deploy/
├─ docs/
├─ freeswitch/
├─ frontend/
├─ gateway/
│  ├─ realtime_gateway.py
│  ├─ gateway_event_listener.py
│  └─ ... (その他gateway関連)
├─ google_stream_asr.py
├─ lib/
├─ libertycall/
│  ├─ gateway/
+│  │  ├─ ai_core.py
│  │  ├─ audio_utils.py
+│  │  └─ text_utils.py
│  ├─ flow_engine/
│  ├─ dialogue_flow/
│  └─ ... (ライブラリ本体)
├─ logs/
├─ Makefile
├─ QUICK_START.md
├─ README.md
├─ requirements.txt
├─ scripts/
├─ setup_env.sh
├─ START_SERVERS.sh
├─ systemd_example.service
├─ tests/
├─ tools/
├─ venv/
└─ VERSION
```

（注）実際のファイル数・深さは多く、サブディレクトリ内にも診断レポートや多数の補助スクリプトがあります。必要であれば完全な再帰ツリーを作成してさらに詳細ファイルごとの要約を作成します。

---

## 12. デリバリノート（別の AI に渡す時のポイント）
- 重要ファイル: `gateway/realtime_gateway.py`, `libertycall/gateway/ai_core.py`, `asr_handler.py` を先に解析させると短時間でアーキテクチャを把握できます。
- 環境依存: FreeSWITCH（`fs_cli`）、Google 認証ファイル、`/tmp/rtp_info_*.txt` の存在に依存する箇所が多いです。モック or テスト環境の準備を推奨。
- ログレベルを INFO→DEBUG に上げて実行することで、ASR／RTP／UUID マッピングなどの詳細な処理を追跡できます。

---

以上。追加で
- 完全な再帰ツリー（全ファイル一覧）、
- ファイルごとの関数シグネチャ一覧（自動抽出）、
- シーケンス図（PlantUML）やER図（必要なら）
を作成できます。どれを先に出力しますか？


