# 最新通話ログ分析報告書（複数アナウンス問題）

**調査日時**: 2025-12-27 20:54頃  
**報告された問題**: 色んなアナウンスが入り乱れている。前の通話が死んでない可能性が非常に高い。

---

## 【1. 問題の概要】

実通話を行った際、複数のアナウンスが同時に再生され、入り乱れている状態が発生。

---

## 【2. 最新の通話ID】

- **最新通話ID**: `in-2025122720503611` (20:52:45開始)
- **前の通話ID**: `in-2025122720494820` (20:49:48開始)

---

## 【3. 重大な発見】

### 3.1 前の通話が終了していない

**通話ID: `in-2025122720494820`**

```
2025-12-27 20:49:48,362 [WARNING] [RTP_RECOVERY] [LOC_01] Time=1766836188.362 call_id=in-2025122720494820 not in active_calls but receiving RTP. Auto-registering.
2025-12-27 20:49:48,427 [INFO] [CALL_START] on_call_start() called for call_id=in-2025122720494820 client_id=000
```

**問題点**:
- ✅ `CALL_START` は呼ばれている
- ❌ **`Removed call_id` が見当たらない**（通話が終了していない）
- ❌ **`CALL_END_TRACE` が見当たらない**（通話が終了していない）

**結論**: この通話が終了せずに残っている可能性が非常に高い。

---

### 3.2 同じ通話が2回開始されている

**通話ID: `in-2025122720503611`**

```
2025-12-27 20:52:45,337 [INFO] [CALL_START] on_call_start() called for call_id=in-2025122720503611 client_id=000
2025-12-27 20:53:19,271 [INFO] [CALL_START] on_call_start() called for call_id=in-2025122720503611 client_id=000
```

**問題点**:
- 同じ通話IDで `CALL_START` が2回呼ばれている（約34秒間隔）
- これにより、同じ通話が重複して処理されている可能性

---

### 3.3 初期アナウンスタスクが完了していない

**ログから確認されたタスク状態**:

```
task: <Task pending name='Task-20' coro=<RealtimeGateway._queue_initial_audio_sequence() done, defined at /opt/libertycall/gateway/realtime_gateway.py:3829> wait_for=<Future pending ...>
task: <Task pending name='Task-2886' coro=<RealtimeGateway._queue_initial_audio_sequence() done, defined at /opt/libertycall/gateway/realtime_gateway.py:3829> wait_for=<Future pending ...>
task: <Task pending name='Task-4742' coro=<RealtimeGateway._queue_initial_audio_sequence() done, defined at /opt/libertycall/gateway/realtime_gateway.py:3829> wait_for=<Future pending ...>
task: <Task pending name='Task-7496' coro=<RealtimeGateway._queue_initial_audio_sequence() done, defined at /opt/libertycall/gateway/realtime_gateway.py:3829> wait_for=<Future pending ...>
task: <Task pending name='Task-3025' coro=<RealtimeGateway._queue_initial_audio_sequence() done, defined at /opt/libertycall/gateway/realtime_gateway.py:3820> wait_for=<Future pending ...>
```

**問題点**:
- 複数の `_queue_initial_audio_sequence` タスクが `pending` のまま
- タスクが完了していないため、初期アナウンスが完了していない
- `[INIT_TASK_START]` は出ているが、`[INIT_TASK_DONE]` や `[INIT_TASK_ERR]` が見当たらない

**初期アナウンス処理のログ**:

```
2025-12-27 20:49:48,427 [WARNING] [INIT_DEBUG] Calling play_incoming_sequence for client=000
2025-12-27 20:52:45,337 [WARNING] [INIT_DEBUG] Calling play_incoming_sequence for client=000
2025-12-27 20:53:19,271 [WARNING] [INIT_DEBUG] Calling play_incoming_sequence for client=000
```

**問題点**:
- `[INIT_DEBUG] Calling play_incoming_sequence` は出ている
- ❌ **その後のログ（`audio_paths result` や `Flag set`）が見当たらない**
- ❌ **`initial_sequence_playing=False` のログが出ていない**（20:49:48以降の通話で）

---

### 3.4 初期アナウンスが完了していない

**20:30:30以前の通話（正常）**:
```
2025-12-27 20:30:29,876 [INFO] [INITIAL_SEQUENCE] ON: client=000 initial_sequence_playing=True
2025-12-27 20:30:30,425 [INFO] [INITIAL_SEQUENCE] OFF: initial_sequence_playing=False -> completed=True
```

**20:49:48以降の通話（異常）**:
- `[INITIAL_SEQUENCE] ON` のログが見当たらない
- `[INITIAL_SEQUENCE] OFF` のログが見当たらない
- 初期アナウンスが完了していない

---

### 3.5 RTP_RECOVERY が頻繁に発生

```
2025-12-27 20:49:48,362 [WARNING] [RTP_RECOVERY] [LOC_01] Time=1766836188.362 call_id=in-2025122720494820 not in active_calls but receiving RTP. Auto-registering.
2025-12-27 20:52:45,215 [WARNING] [RTP_RECOVERY] [LOC_01] Time=1766836365.216 call_id=in-2025122720503611 not in active_calls but receiving RTP. Auto-registering.
```

**問題点**:
- 通話が `_active_calls` から削除された後もRTPパケットが来ている
- RTP_RECOVERY により通話が復活している
- これが原因で複数の通話が同時に動いている可能性

---

## 【4. 原因の推測】

### 4.1 通話終了処理が正しく動作していない

- `in-2025122720494820` が終了していない
- `Removed call_id` や `CALL_END_TRACE` が見当たらない
- 通話が `_active_calls` から削除されていない

### 4.2 初期アナウンスタスクがブロックしている

- `_queue_initial_audio_sequence` のタスクが `pending` のまま
- タスクが完了していないため、初期アナウンスが完了していない
- 複数のタスクが同時に実行されている可能性

### 4.3 同じ通話が重複して処理されている

- 同じ通話IDで `CALL_START` が2回呼ばれている
- これにより、同じ通話が重複して処理されている

### 4.4 RTP_RECOVERY による通話の復活

- 通話が終了した後もRTPパケットが来ている
- RTP_RECOVERY により通話が復活している
- これが原因で複数の通話が同時に動いている

---

## 【5. 確認が必要な項目】

### 5.1 通話終了処理の確認

- `handle_hangup` が正しく呼ばれているか
- `_active_calls` から通話が削除されているか
- `CALL_END_TRACE` が出力されているか

### 5.2 初期アナウンスタスクの確認

- `_queue_initial_audio_sequence` が正しく完了しているか
- タスクがブロックしていないか
- `run_in_executor` が正しく動作しているか

### 5.3 通話の重複処理の確認

- 同じ通話IDで `CALL_START` が複数回呼ばれないようにする
- `_active_calls` に既に存在する通話IDをチェックする

### 5.4 RTP_RECOVERY の動作確認

- RTP_RECOVERY が正しく動作しているか
- 終了した通話を復活させないようにする

---

## 【6. 推奨される修正方針】

### 6.1 通話終了処理の強化

- `handle_hangup` で確実に `_active_calls` から削除する
- 通話終了時にすべてのタスクをキャンセルする
- 通話終了ログを確実に出力する

### 6.2 初期アナウンスタスクの改善

- タスクが完了するまで待つ（またはタイムアウトを設定）
- タスクがブロックしないようにする
- エラーハンドリングを追加する

### 6.3 通話の重複処理の防止

- `CALL_START` 時に `_active_calls` に既に存在するかチェックする
- 既に存在する場合は、既存の通話を終了してから新しい通話を開始する

### 6.4 RTP_RECOVERY の改善

- 終了した通話を復活させないようにする
- RTP_RECOVERY の条件を厳しくする

---

## 【7. 結論】

**問題の根本原因**:
1. **前の通話（`in-2025122720494820`）が終了していない**
2. **初期アナウンスタスクが完了していない**
3. **同じ通話が重複して処理されている**
4. **RTP_RECOVERY により通話が復活している**

**影響**:
- 複数のアナウンスが同時に再生される
- 通話が正常に終了しない
- システムリソースの無駄遣い

**緊急度**: **高** - 本番環境で発生している問題のため、早急な対応が必要

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 20:55

