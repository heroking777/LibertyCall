# LibertyCall コーディングガイドライン

## プロジェクト概要
AI電話受付代行サービス。FreeSWITCHで着信を受け、対話フローエンジンでルールベース応答を決定し、事前生成済み音声を再生して返す。

## 技術スタック
- FreeSWITCH（PBX/SIP/ESL接続）
- Python 3.12（Gateway、ASR、API）
- 対話フローエンジン（ルールベース：FlowEngine + IntentClassifier）
- 事前生成済み音声（clients/{client_id}/audio/*.wav をテンプレートIDで再生）
- Gemini TTS（音声の事前生成に使用。通話中のリアルタイム合成ではない）
- WebSocket（Gateway⇔コンソール通信）
- Flask（LP問い合わせAPI）
- AWS SES（メール送信）
- nginx（リバースプロキシ）
- SQLite（通話ログDB）

## ディレクトリ構成
- `gateway/` - メインゲートウェイ（通話処理・AI応答）
- `gateway/core/` - ゲートウェイコアモジュール（33ファイル）
- `gateway/dialogue/` - 対話エンジン（FlowEngine、IntentClassifier、PromptFactory）
- `clients/` - クライアント別設定・事前生成済み音声（audio/*.wav）
- `freeswitch/` / `freeswitch_conf/` - FreeSWITCH設定
- `asr/` / `asr_stream/` - 音声認識
- `console_backend/` - 管理コンソール
- `lp/` - ランディングページ・問い合わせAPI
- `email_sender/` - メール送信テンプレート
- `libs/` - ESLライブラリ等
- `models/` - DBモデル

## セキュリティルール
- シークレット（APIキー、パスワード）は環境変数または.envで管理。コードにハードコード禁止
- .envはgitignoreに含める
- AWS認証情報はIAMロールまたは環境変数で管理

## コーディング規約
- ログは`self.logger`または`logging`モジュールを使用
- 通話状態の変更は`call_session_store`経由
- 転送後はASR停止・AI応答無効化を確認（`transfer_executed`フラグ）
- FreeSWITCH操作はESL経由（`gateway_esl_manager.py`）
- エラーハンドリングは必ずtry-exceptで囲む

## レガシー命名に関する注意
- 一部のメソッド名・ログに「Asterisk」が残っているがレガシー命名
- 実際のPBXはFreeSWITCH。リネームは影響範囲が大きいため現状維持
