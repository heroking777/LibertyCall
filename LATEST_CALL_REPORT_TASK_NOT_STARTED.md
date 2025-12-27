# 最新通話ログ調査報告書（タスクが開始されない問題）

**調査日時**: 2025-12-27 20:24頃  
**対象通話ID**: `in-2025122720231909`  
**報告された問題**: 音声反応なし

---

## 【1. 通話開始時の状況】

### 通話開始フロー

1. **20:23:19.146**: `[RTP_RECOVERY] [LOC_01]` - 自動登録
2. **20:23:19.147**: `[DEBUG_PRINT] _queue_initial_audio_sequence called` - **関数呼び出しは確認**
3. **20:23:19.147**: `[INIT_SEQ] Queueing initial sequence for in-2025122720231909 (first time).`
4. **20:23:19.147**: `[DEBUG_PRINT] calling on_call_start`
5. **20:23:19.148**: `[CALL_START] on_call_start() called`
6. **20:23:19.705**: `[ASR_DEBUG] Calling on_new_audio` - ASRへの音声送信開始

### 初期アナウンス処理の状況

**見つからないログ**:
- ❌ `[INIT_TASK_START] Created task for ...` - タスク生成ログ
- ❌ `[INIT_METHOD_ENTRY] Called with client_id=...` - 関数エントリーログ
- ❌ `[INIT_TASK_ERR]` - タスクエラーログ
- ❌ `[INIT_DEBUG] Calling play_incoming_sequence for client=...` - 前回追加したログ
- ❌ `[INIT_DEBUG] audio_paths result: ...` - 前回追加したログ
- ❌ `[INIT_SEQ] Flag set for ... Queued ... chunks.` - キュー追加成功後のログ

**観察**:
- `[DEBUG_PRINT] _queue_initial_audio_sequence called`ログは出力されている
- しかし、`[INIT_TASK_START]`ログが見つからない
- **`asyncio.create_task`が呼ばれていない可能性**
- または、`asyncio.create_task`が呼ばれても、タスクが即座にクラッシュしている可能性
- **重要な矛盾**: `[DEBUG_PRINT] _queue_initial_audio_sequence called`ログは`_queue_initial_audio_sequence`メソッド内のtryブロック内で出力されているが、`[INIT_METHOD_ENTRY]`ログ（メソッドの最初の行）が見つからない

---

## 【2. 矛盾点の分析】

### ログの出力位置

**`[INIT_METHOD_ENTRY]`ログ**:
- 位置: `_queue_initial_audio_sequence`メソッドの最初（tryブロックの外、3831行目）
- 条件: メソッドが呼ばれれば必ず出力される

**`[DEBUG_PRINT] _queue_initial_audio_sequence called`ログ**:
- 位置: `_queue_initial_audio_sequence`メソッド内のtryブロック内（3839行目）
- 条件: メソッドが呼ばれ、tryブロックに入れば出力される

**矛盾**:
- `[DEBUG_PRINT] _queue_initial_audio_sequence called`ログは出力されている
- しかし、`[INIT_METHOD_ENTRY]`ログが見つからない
- **これは、メソッドが呼ばれているが、最初の行が実行されていないことを示唆**

### 可能性のある原因

1. **古いコードが実行されている**
   - サービスが再起動されていない
   - または、別のプロセスが実行されている

2. **`[DEBUG_PRINT] _queue_initial_audio_sequence called`ログが別の場所から出力されている**
   - しかし、grepの結果から、このログは`_queue_initial_audio_sequence`メソッド内でしか出力されていないことが確認できた

3. **メソッドが同期関数として呼ばれている**
   - `await`なしで呼ばれている可能性
   - しかし、`async def`で定義されているので、`await`なしでは呼べない

---

## 【3. ASRへの音声送信状況】

### 音声送信の確認

**RMS値の変化**:
- **20:23:19.205**: `rms=1` (無音)
- **20:23:19.404**: `rms=1` (無音)
- **20:23:19.604**: `rms=2` (無音)
- **20:23:19.785**: `rms=2` (無音)
- **20:23:19.805**: `rms=2` (無音)

**観察**:
- RMS値は低い（1-2程度）ので、音声は検出されていない（無音）
- `on_new_audio`は正常に呼ばれている
- `STREAMING_FEED`ログも正常に出力されている

### ASRへの音声送信タイミング

**20:23:19.705-20:23:20.426**:
- 連続して`on_new_audio`が呼ばれている
- RMS値が低い（1-2程度）ので、音声は検出されていない（無音）

---

## 【4. ASRリクエスト送信の生存確認】

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

## 【5. ASRレスポンスの確認】

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

## 【6. 現在のアクティブな通話本数】

### ログからの確認

**最新の`_active_calls`操作**:
- **20:21:59.998**: `[CALL_END_TRACE] [LOC_02] Discarding call_id=in-2025122720203034 from _active_calls`
- **現在のアクティブな通話**: **0本**（通話は終了している）

---

## 【7. 問題の原因分析】

### 可能性のある原因

1. **古いコードが実行されている**
   - サービスが再起動されていない
   - または、別のプロセスが実行されている
   - **最も可能性が高い**

2. **`asyncio.create_task`が呼ばれていない**
   - `[INIT_TASK_START]`ログが見つからない
   - `[DEBUG_PRINT] _queue_initial_audio_sequence called`ログは出力されている
   - **`handle_rtp_packet`内で`_queue_initial_audio_sequence`が直接呼ばれている可能性**

3. **タスク生成時の即時クラッシュ**
   - `asyncio.create_task`が呼ばれても、タスクが即座にクラッシュしている可能性
   - しかし、`[INIT_TASK_ERR]`ログも見つからない

4. **ASRストリームが開始されていない**
   - `[ASR_REQ_ALIVE]`ログが見つからない
   - ASRストリームが開始されていない可能性

---

## 【8. 推奨事項】

### 1. サービス再起動の確認
- サービスが正しく再起動されているか確認
- 実行中のプロセスを確認
- 古いコードが実行されていないか確認

### 2. `handle_rtp_packet`内の呼び出し確認
- `handle_rtp_packet`内で`_queue_initial_audio_sequence`がどのように呼ばれているか確認
- `asyncio.create_task`が呼ばれているか確認
- 直接（同期）呼び出しになっていないか確認

### 3. タスク生成の確認
- `asyncio.create_task`呼び出し前後のログを追加
- タスクが生成されたことを確認するログを追加

### 4. ASRストリーム開始の確認
- GoogleASRのストリーム開始ログを確認
- ASRが有効化されているか確認
- `[ASR_REQ_ALIVE]`ログが出力されていない理由を確認

---

## 【9. 結論】

### 修正の効果
- ✅ コールバック追加は実装された（`add_done_callback`）
- ✅ 関数エントリーログは追加された（`[INIT_METHOD_ENTRY]`）
- ❌ しかし、`[INIT_TASK_START]`ログが出力されていない（タスクが生成されていない可能性）
- ❌ `[INIT_METHOD_ENTRY]`ログが出力されていない（メソッドが呼ばれていない可能性）
- ❌ 初期アナウンス処理のログ（`[INIT_DEBUG]`）が見つからない
- ❌ ASRリクエスト送信の生存確認ログ（`[ASR_REQ_ALIVE]`）が出力されていない
- ❌ ASRからのレスポンスが来ていない（`[ASR_RAW_RES]`ログ）

### 新たに発見された問題
1. **矛盾するログ出力**
   - `[DEBUG_PRINT] _queue_initial_audio_sequence called`ログは出力されている
   - しかし、`[INIT_METHOD_ENTRY]`ログが見つからない
   - **古いコードが実行されている可能性が高い**

2. **`asyncio.create_task`が呼ばれていない**
   - `[INIT_TASK_START]`ログが見つからない
   - `[DEBUG_PRINT] _queue_initial_audio_sequence called`ログは出力されている
   - **`handle_rtp_packet`内で`_queue_initial_audio_sequence`が直接呼ばれている可能性**

3. **ASRストリームが開始されていない**
   - `[ASR_REQ_ALIVE]`ログが見つからない
   - ASRストリームが開始されていない可能性

### 次のステップ
1. **サービス再起動の確認**（最優先）
2. `handle_rtp_packet`内の呼び出し確認（`asyncio.create_task`が呼ばれているか）
3. タスク生成の確認（`asyncio.create_task`呼び出し前後のログ）
4. ASRストリーム開始の確認（GoogleASRのストリーム開始ログ）

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 20:24
