# Gateway コードレビュー指針

## 対象ファイル
- `gateway/core/*.py`（33モジュール）
- `gateway/realtime_gateway.py`
- `gateway/asr_controller.py`
- `gateway/intent_rules.py`
- `gateway/dialogue/`（フローエンジン、意図分類、プロンプト生成）

## アーキテクチャ
```
電話着信 → FreeSWITCH → ESL → Gateway
                                  ↓
                        ASR（音声認識）→ IntentClassifier
                                  ↓
                        FlowEngine（ルールベース応答決定）
                                  ↓
                        テンプレートID → clients/{id}/audio/*.wav → FreeSWITCHで再生
```

## 音声再生フロー
1. FlowEngineが応答テンプレートIDを決定
2. clients/{client_id}/audio/ から該当wavファイルを取得
3. FreeSWITCH ESL経由でuuid_broadcastまたはplaybackで再生
※ 通話中のリアルタイムTTS合成は行わない。音声は全て事前生成済み

## 重要モジュール
- `ai_core.py` - 応答のメインクラス。フロー実行・テンプレート音声再生・転写保存を統括
- `call_lifecycle_handler.py` - 通話開始・転送・切断のライフサイクル管理
- `call_session_store.py` - 通話状態の一元管理
- `gateway_esl_manager.py` - FreeSWITCH ESL接続管理
- `monitor_manager.py` - FreeSWITCH RTPポート監視（ASR用音声取得）
- `call_manager.py` - 転送トリガー管理
- `gateway_event_router.py` - WebSocketイベントルーティング

## レビュー観点
- 通話状態の競合（複数スレッドからの同時アクセス）
- 転送後のASR/AI応答停止漏れ
- ESL接続のエラーハンドリング・再接続
- メモリリーク（通話終了後のセッションクリーンアップ）
- RTPポート監視の安定性
- FreeSWITCH UUIDマッピングの整合性
- 音声テンプレートIDの存在チェック（wavファイルが見つからない場合のフォールバック）
