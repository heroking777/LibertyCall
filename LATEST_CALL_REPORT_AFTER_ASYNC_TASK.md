# 最新通話ログ調査報告書（非同期タスク化後の状況）

**調査日時**: 2025-12-27 20:17頃  
**対象通話ID**: `in-2025122720164428`  
**報告された問題**: 音声に対する反応なし

---

## 【1. 通話開始時の状況】

### 通話開始フロー

1. **20:16:44.251**: `[RTP_RECOVERY] [LOC_01]` - 自動登録
2. **20:16:44.251**: `[DEBUG_PRINT] _queue_initial_audio_sequence called`
3. **20:16:44.252**: `[INIT_SEQ] Queueing initial sequence for in-2025122720164428 (first time).`
4. **20:16:44.252**: `[DEBUG_PRINT] calling on_call_start`
5. **20:16:44.252**: `[CALL_START] on_call_start() called`
6. **20:16:44.810**: `[ASR_DEBUG] Calling on_new_audio` - ASRへの音声送信開始

### 初期アナウンス処理の状況

**見つからないログ**:
- ❌ `[INIT_TASK] Task started for client_id=...` - 前回追加したタスク開始ログ
- ❌ `[INIT_DEBUG] Calling play_incoming_sequence for client=...` - 前回追加したログ
- ❌ `[INIT_DEBUG] audio_paths result: ...` - 前回追加したログ
- ❌ `[INIT_DEBUG] Processing audio_path[0]=...` - 前回追加したログ
- ❌ `[INIT_ERR]` - エラーログ（例外が発生していない可能性）
- ❌ `[INIT_SEQ] Flag set for ... Queued ... chunks.` - キュー追加成功後のログ
- ❌ `initial greeting enqueued` - キュー追加完了ログ

**観察**:
- `[INIT_SEQ] Queueing initial sequence`ログは出力されている
- しかし、その後の`[INIT_TASK]`ログが見つからない
- **非同期タスクが開始されていない可能性**

---

## 【2. ASRへの音声送信状況】

### 音声送信の確認

**RMS値の変化**:
- **20:16:44.310**: `rms=19` (初期)
- **20:16:44.509**: `rms=5` (無音)
- **20:16:44.710**: `rms=5` (無音)
- **20:16:44.810**: `rms=4` (無音)
- **20:16:45.010**: `rms=163` (音声検出)
- **20:16:45.109**: `rms=33` (音声検出)
- **20:16:45.510**: `rms=42` (音声検出)

**観察**:
- RMS値は低い（1-163程度）ので、音声は検出されているが小さい
- `on_new_audio`は正常に呼ばれている
- `STREAMING_FEED`ログも正常に出力されている

### ASRへの音声送信タイミング

**20:16:44.810-20:16:45.510**:
- 連続して`on_new_audio`が呼ばれている
- RMS値が低い（1-163程度）ので、音声は検出されているが小さい

---

## 【3. ASRリクエスト送信の生存確認】

### ASRリクエスト送信ログの検索結果

**見つからないログ**:
- ❌ `[ASR_REQ_ALIVE]`ログが見つからない
- ❌ `[REQUEST_GEN]`ログが見つからない
- ❌ `[STREAM_WORKER]`ログが見つからない

**観察**:
- ASRへの音声送信は正常（`on_new_audio`が呼ばれている）
- しかし、ASRリクエスト送信の生存確認ログが見つからない
- **ASRストリームが開始されていない可能性**

---

## 【4. ASRレスポンスの確認】

### ASRレスポンスログの検索結果

**見つからないログ**:
- ❌ `[ASR_RAW_RES]`ログが見つからない
- ❌ `[ASR_TRANSCRIPT]`ログが見つからない
- ❌ `[ASR_GOOGLE_RAW]`ログが見つからない

**観察**:
- ASRへの音声送信は正常
- しかし、ASRからのレスポンスが来ていない
- Google Speech-to-Text APIからのレスポンスが来ていない可能性

---

## 【5. 現在のアクティブな通話本数】

### ログからの確認

**最新の`_active_calls`操作**:
- **20:11:59.713**: `[CALL_END_TRACE] [LOC_02] Discarding call_id=in-2025122720094140 from _active_calls`
- **現在のアクティブな通話**: **0本**（通話は終了している）

---

## 【6. 問題の原因分析】

### 可能性のある原因

1. **非同期タスクが開始されていない**
   - `[INIT_TASK] Task started`ログが出力されていない
   - `asyncio.create_task`が正しく実行されていない可能性
   - または、タスクが開始されたが、すぐに例外で終了している可能性

2. **初期アナウンス処理が途中で中断している**
   - `[INIT_DEBUG] Calling play_incoming_sequence`ログが出力されていない
   - `play_incoming_sequence`呼び出し前に処理が中断している可能性
   - エラーログ（`[INIT_ERR]`）も見つからないので、例外が発生していない可能性

3. **ASRストリームが開始されていない**
   - `[ASR_REQ_ALIVE]`ログが見つからない
   - ASRストリームが開始されていない可能性

4. **音声が小さすぎる**
   - RMS値が低い（1-163程度）ので、音声は検出されているが小さい
   - ASRが音声を認識できない可能性

---

## 【7. 推奨事項】

### 1. 非同期タスクの開始確認
- `asyncio.create_task`が正しく実行されているか確認
- タスクが開始されたが、すぐに例外で終了していないか確認
- `[INIT_TASK]`ログが出力されていない理由を確認

### 2. 初期アナウンス処理の確認
- `play_incoming_sequence`呼び出し前の処理が正常に実行されているか確認
- エラーログが出力されていない理由を確認

### 3. ASRストリーム開始の確認
- GoogleASRのストリーム開始ログを確認
- ASRが有効化されているか確認
- `[ASR_REQ_ALIVE]`ログが出力されていない理由を確認

### 4. ログの追加
- `asyncio.create_task`呼び出し前後のログを追加
- タスクが開始されたことを確認するログを追加

---

## 【8. 結論】

### 修正の効果
- ✅ 非同期タスク化は実装された（`async def`と`asyncio.create_task`）
- ❌ しかし、`[INIT_TASK]`ログが出力されていない（タスクが開始されていない可能性）
- ❌ 初期アナウンス処理のログ（`[INIT_DEBUG]`）が見つからない
- ❌ ASRリクエスト送信の生存確認ログ（`[ASR_REQ_ALIVE]`）が出力されていない
- ❌ ASRからのレスポンスが来ていない（`[ASR_RAW_RES]`ログ）

### 新たに発見された問題
1. **非同期タスクが開始されていない**
   - `[INIT_TASK] Task started`ログが出力されていない
   - `asyncio.create_task`が正しく実行されていない可能性

2. **初期アナウンス処理が途中で中断している**
   - `[INIT_DEBUG] Calling play_incoming_sequence`ログが出力されていない
   - `play_incoming_sequence`呼び出し前に処理が中断している可能性

3. **ASRストリームが開始されていない**
   - `[ASR_REQ_ALIVE]`ログが見つからない
   - ASRストリームが開始されていない可能性

### 次のステップ
1. 非同期タスクの開始確認（`asyncio.create_task`が正しく実行されているか）
2. 初期アナウンス処理の確認（`play_incoming_sequence`呼び出し前の処理）
3. ASRストリーム開始の確認（GoogleASRのストリーム開始ログ）
4. ログの追加（`asyncio.create_task`呼び出し前後、タスク開始確認）

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 20:17

