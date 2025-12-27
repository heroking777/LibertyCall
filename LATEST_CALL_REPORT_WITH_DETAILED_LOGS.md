# 最新通話ログ分析報告書（詳細ログ追加後のテスト結果）

**調査日時**: 2025-12-27 21:15頃  
**対象通話ID**: `in-2025122721145821`  
**報告された問題**: 初回アナウンスあり、ASR反応なし、催促アナウンスあり

---

## 【1. 通話の概要】

- **通話開始**: 2025-12-27 21:14:58
- **通話ID**: `in-2025122721145821`
- **クライアントID**: `000`
- **通話終了**: 2025-12-27 21:15:31（約33秒）
- **通話ログ行数**: 6,402行

---

## 【2. 新規追加ログの確認結果】

### ✅ 初期アナウンスファイル取得ログ（[PLAY_SEQ_]）

**確認されたログ**:
```
2025-12-27 21:14:58,979 [WARNING] [PLAY_SEQ_START] play_incoming_sequence called for client_id=000
2025-12-27 21:14:58,979 [WARNING] [PLAY_SEQ_CLIENTS] Failed to list clients: 'ClientConfigLoader' object has no attribute 'list_clients'
2025-12-27 21:14:58,979 [WARNING] [PLAY_SEQ_CLIENT_DATA] sequence=[]
2025-12-27 21:14:58,979 [WARNING] [PLAY_SEQ_AUDIO_PATHS] audio_paths=[] (count=0)
```

**評価**:
- ✅ `[PLAY_SEQ_START]` が出力されている
- ⚠️ `[PLAY_SEQ_CLIENTS]` でエラーが発生している（`list_clients` メソッドが存在しない）
- ❌ **`[PLAY_SEQ_CLIENT_DATA] sequence=[]` - 空のリストが返ってきている（最重要の問題）**
- ❌ **`[PLAY_SEQ_AUDIO_PATHS] audio_paths=[] (count=0)` - 空のリストが返ってきている**

---

### ✅ ASRストリーム初期化ログ（[ASR_STREAM_]）

**確認されたログ**:
```
2025-12-27 21:15:03,513 [WARNING] [ASR_STREAM_INIT] StreamingRecognitionConfig created: interim=False, single_utterance=False
2025-12-27 21:15:03,514 [WARNING] [ASR_STREAM_START] streaming_recognize started for call_id=unknown
2025-12-27 21:15:03,515 [WARNING] [ASR_STREAM_ITER] Starting to iterate responses
```

**評価**:
- ✅ `[ASR_STREAM_INIT]` が出力されている
- ✅ `[ASR_STREAM_START]` が出力されている
- ✅ `[ASR_STREAM_ITER]` が出力されている
- ⚠️ `call_id=unknown` となっている（call_idが正しく渡されていない可能性）
- ❌ **`[ASR_RESPONSE_RECEIVED]` が見当たらない（ASRレスポンスが返ってきていない）**

---

## 【3. 確認結果サマリー】

### ✅ 正常に動作している項目

1. **通話開始処理**
   - `[CALL_START]` が正常に呼ばれている
   - `on_call_start()` が実行されている
   - `_active_calls` に追加されている

2. **タイムアウト処理**
   - `[INIT_TIMEOUT_START]` が出力されている
   - `[INIT_TIMEOUT_SUCCESS]` が出力されている（タイムアウト内に完了）
   - `[INIT_FINALLY]` が出力されている

3. **RTPパケット受信**
   - RTPパケットは正常に受信されている
   - `STREAMING_FEED` ログが正常に出力されている

4. **ASRへの音声送信**
   - `on_new_audio` が正常に呼ばれている
   - `QUEUE_PUT` が正常に出力されている
   - 音声データはASRに送信されている

5. **ASRストリーム初期化**
   - `[ASR_STREAM_INIT]` が出力されている
   - `[ASR_STREAM_START]` が出力されている
   - `[ASR_STREAM_ITER]` が出力されている

6. **通話終了処理（部分的）**
   - `on_call_end()` が呼ばれている
   - 転送処理（`TRANSFER_TO_OPERATOR`）が実行されている

---

## 【4. 問題が発見された項目】

### 4.1 初期アナウンスシーケンスが空（最重要）

**発見された問題**:
- ❌ `[PLAY_SEQ_CLIENT_DATA] sequence=[]` - 空のリストが返ってきている
- ❌ `[PLAY_SEQ_AUDIO_PATHS] audio_paths=[] (count=0)` - 空のリストが返ってきている

**ログ確認結果**:
```
2025-12-27 21:14:58,979 [WARNING] [PLAY_SEQ_CLIENT_DATA] sequence=[]
2025-12-27 21:14:58,979 [WARNING] [PLAY_SEQ_AUDIO_PATHS] audio_paths=[] (count=0)
```

**問題点**:
- `get_incoming_sequence(client_id)` が空のリストを返している
- クライアントID `000` の着信シーケンス設定が存在しない、または読み込めていない
- 初期アナウンスファイルが取得できていない

**影響**:
- 初期アナウンスが再生されない
- ユーザーは「初回アナウンスあり」と報告しているが、これは別の方法（FreeSWITCH側など）で再生されている可能性

---

### 4.2 ASRレスポンスが返ってきていない

**発見された問題**:
- ❌ `[ASR_RESPONSE_RECEIVED]` のログが見当たらない
- ❌ `[ASR_RAW_RES]` のログが見当たらない
- ❌ `[ASR_TRANSCRIPT]` のログが見当たらない

**ログ確認結果**:
- ✅ `[ASR_STREAM_INIT]` が出力されている
- ✅ `[ASR_STREAM_START]` が出力されている
- ✅ `[ASR_STREAM_ITER]` が出力されている
- ✅ `on_new_audio` は正常に呼ばれている
- ✅ `QUEUE_PUT` は正常に出力されている
- ❌ しかし、`[ASR_RESPONSE_RECEIVED]` が見当たらない

**問題点**:
- ASRストリームは初期化されているが、レスポンスが返ってきていない
- Google ASRからのレスポンスが返ってこない可能性
- `for response in responses:` ループ内でレスポンスが来ていない

**影響**:
- ASRが反応しない
- ユーザーの発話が認識されない

---

### 4.3 通話終了処理のfinallyブロックが実行されていない

**発見された問題**:
- ❌ `[HANGUP_DONE]` のログが見当たらない
- ❌ `[COMPLETE_CALL_DONE]` のログが見当たらない
- ❌ `[EVENT_SOCKET_DONE]` のログが見当たらない

**ログ確認結果**:
```
2025-12-27 21:15:31,731 [INFO] [AICORE] on_call_end() call_id=in-2025122721145821 source=gateway_event_listener
2025-12-27 21:15:31,741 [INFO] [EVENT_SOCKET] on_call_end() called for call_id=in-2025122721145821
2025-12-27 21:15:33,529 [INFO] [ASRHandler] Executed: hangup NORMAL_CLEARING (call_id=in-2025122721145821)
```

**問題点**:
- `on_call_end()` は呼ばれているが、`finally` ブロックが実行されていない
- `event_socket` の `call_end` イベント処理で `finally` ブロックが実行されていない可能性
- `_active_calls` から削除されていない可能性

**影響**:
- `_active_calls` から削除されていない可能性
- 管理用データ（`_recovery_counts` など）がクリーンアップされていない可能性
- ゾンビ通話が発生する可能性

---

### 4.4 ASRストリームのcall_idがunknown

**発見された問題**:
- ⚠️ `[ASR_STREAM_START] streaming_recognize started for call_id=unknown`

**ログ確認結果**:
```
2025-12-27 21:15:03,514 [WARNING] [ASR_STREAM_START] streaming_recognize started for call_id=unknown
```

**問題点**:
- `GoogleStreamingASR` オブジェクトに `call_id` 属性が設定されていない
- `getattr(self, 'call_id', 'unknown')` で `unknown` が返されている

**影響**:
- ログで通話IDを追跡できない
- デバッグが困難になる

---

## 【5. 原因の推測】

### 5.1 初期アナウンスシーケンスが空

- `get_incoming_sequence(client_id)` が空のリストを返している
- クライアントID `000` の着信シーケンス設定ファイルが存在しない、または読み込めていない
- `ClientConfigLoader.load_incoming_sequence()` が空のリストを返している可能性

### 5.2 ASRレスポンスが返ってきていない

- Google ASRストリームは初期化されているが、レスポンスが返ってこない
- `for response in responses:` ループ内でレスポンスが来ていない
- Google ASR APIとの接続に問題がある可能性
- 認証情報やネットワークの問題の可能性

### 5.3 通話終了処理のfinallyブロックが実行されていない

- `event_socket` の `call_end` イベント処理で `finally` ブロックが実行されていない
- エラーが発生して `finally` ブロックに到達していない可能性
- または、`finally` ブロック内の条件分岐で実行されていない可能性

---

## 【6. 確認が必要な項目】

### 6.1 初期アナウンスシーケンス設定の確認

- クライアントID `000` の着信シーケンス設定ファイルが存在するか
- `ClientConfigLoader.load_incoming_sequence()` の実装を確認
- 設定ファイルのパスと内容を確認

### 6.2 ASRレスポンスが返ってこない原因の確認

- Google ASR APIとの接続状態を確認
- 認証情報が正しいか確認
- ネットワーク接続を確認
- `for response in responses:` ループが正常に動作しているか確認

### 6.3 通話終了処理のfinallyブロック実行確認

- `event_socket` の `call_end` イベント処理で `finally` ブロックが実行されているか
- エラーが発生していないか確認
- 条件分岐で実行されていない可能性を確認

### 6.4 ASRストリームのcall_id設定確認

- `GoogleStreamingASR` オブジェクトに `call_id` 属性を設定する処理を追加
- ログで通話IDを追跡できるようにする

---

## 【7. 推奨される修正方針】

### 7.1 初期アナウンスシーケンス設定の修正

- クライアントID `000` の着信シーケンス設定ファイルを確認・作成
- `ClientConfigLoader.load_incoming_sequence()` の実装を確認
- 設定ファイルが存在しない場合のエラーハンドリングを追加

### 7.2 ASRレスポンスが返ってこない原因の調査

- Google ASR APIとの接続状態を確認
- 認証情報を確認
- ネットワーク接続を確認
- `for response in responses:` ループにタイムアウトやエラーハンドリングを追加

### 7.3 通話終了処理のfinallyブロック実行改善

- `event_socket` の `call_end` イベント処理で `finally` ブロックが実行されることを確認
- エラーハンドリングを追加
- 条件分岐を確認

### 7.4 ASRストリームのcall_id設定改善

- `GoogleStreamingASR` オブジェクトに `call_id` 属性を設定する処理を追加
- ログで通話IDを追跡できるようにする

---

## 【8. 結論】

**新規ログ追加の効果**:
- ✅ 初期アナウンスファイル取得処理のログが出力されている
- ✅ ASRストリーム初期化処理のログが出力されている
- ✅ 問題の原因が明確になった

**発見された根本原因**:
1. ❌ **初期アナウンスシーケンスが空**（`sequence=[]`）- これが最重要の問題
2. ❌ **ASRレスポンスが返ってきていない**（`[ASR_RESPONSE_RECEIVED]` が見当たらない）
3. ❌ **通話終了処理のfinallyブロックが実行されていない**（`_active_calls` から削除されていない可能性）

**緊急度**: **高** - 本番環境で発生している問題のため、早急な対応が必要

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 21:16

