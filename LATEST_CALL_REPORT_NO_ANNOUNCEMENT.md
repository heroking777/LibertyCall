# 最新通話ログ調査報告書（アナウンスが流れない問題）

**調査日時**: 2025-12-27 19:55頃  
**対象通話ID**: `in-2025122719534379`  
**報告された問題**: アナウンスが永遠に流れない（初回アナウンスも催促アナウンスもなし）

---

## 【1. 通話開始時の状況】

### 通話開始フロー

1. **19:53:43.716**: `[FS_RTP_MONITOR] Mapped call_id=in-2025122719534379`
2. **19:53:45.751**: `[RTP_RECOVERY] [LOC_01]` - 自動登録
3. **19:53:45.751**: `[DEBUG_PRINT] _queue_initial_audio_sequence called`
4. **19:53:45.751**: `[INIT_SEQ] Queueing initial sequence for in-2025122719534379 (first time).` - **フラグがセットされている**
5. **19:53:45.751**: `[DEBUG_PRINT] calling on_call_start`
6. **19:53:45.751**: `[CALL_START] on_call_start() called`
7. **19:53:47.770**: `[PLAY_TTS] dispatching (initial) text='はい...'` - **`on_call_start`内で実行**

### 問題点

**初期音声シーケンスの処理ログが見つからない**:
- `[client=000] initial greeting files=`ログが見つからない
- `[client=000] initial silence queued`ログが見つからない
- `[client=000] initial queue order=`ログが見つからない
- `[client=000] incoming call audio sequence:`ログが見つからない

**観察**:
- `[INIT_SEQ] Queueing initial sequence`ログは出力されている
- しかし、その後の`audio_paths`取得やキューへの追加のログが見つからない
- フラグがセットされた後、処理が中断されている可能性

---

## 【2. フラグセットのタイミング】

### 現在の実装

**フラグセットのタイミング**:
```python
# フラグをセット（effective_call_idが確定している場合のみ）
if effective_call_id:
    self._initial_sequence_played.add(effective_call_id)
    self.logger.warning(f"[INIT_SEQ] Queueing initial sequence for {effective_call_id} (first time).")
```

**問題点**:
- フラグがセットされるタイミングが、`audio_paths`取得の**前**である
- もし`audio_paths`が空の場合、または処理中にエラーが発生した場合でも、フラグは既にセットされている
- そのため、後で`audio_paths`が取得できても、処理がスキップされる可能性

---

## 【3. 初期音声シーケンスの処理フロー】

### 期待される処理フロー

1. `_queue_initial_audio_sequence`が呼ばれる
2. フラグをチェック（既に実行済みならスキップ）
3. **フラグをセット** ← **問題の可能性**
4. `audio_paths = self.audio_manager.play_incoming_sequence(effective_client_id)`
5. `audio_paths`が空でない場合、キューに追加
6. `queued_chunks > 0`の場合、`self.is_speaking_tts = True`を設定

### 実際の処理フロー

1. `_queue_initial_audio_sequence`が呼ばれる
2. フラグをチェック（未実行）
3. **フラグをセット** ← **ここでセットされている**
4. `on_call_start()`が呼ばれる
5. `[PLAY_TTS] dispatching (initial) text='はい...'`が出力される
6. **その後の処理ログが見つからない**

---

## 【4. 問題の原因分析】

### 可能性のある原因

1. **フラグセットのタイミングが早すぎる**
   - フラグが`audio_paths`取得の前にセットされている
   - もし`audio_paths`が空の場合、または処理中にエラーが発生した場合でも、フラグは既にセットされている
   - そのため、後で`audio_paths`が取得できても、処理がスキップされる可能性

2. **`audio_paths`が空である**
   - `audio_manager.play_incoming_sequence()`が空のリストを返している可能性
   - その場合、`queued_chunks`が0になり、`self.is_speaking_tts = True`が設定されない

3. **処理が中断されている**
   - `audio_paths`取得後にエラーが発生し、処理が中断されている可能性
   - しかし、エラーログが見つからない

4. **`on_call_start()`内で処理が中断されている**
   - `on_call_start()`内で例外が発生し、その後の処理が実行されていない可能性
   - しかし、`[PLAY_TTS] dispatching (initial) text='はい...'`は出力されている

---

## 【5. 現在のアクティブな通話本数】

### ログからの確認

**最新の`_active_calls`操作**:
- **19:53:45.751**: `[RTP_RECOVERY]` - 自動登録
- **現在のアクティブな通話**: **0本**（通話は終了している）

---

## 【6. 推奨事項】

### 1. フラグセットのタイミングを変更
- フラグをセットするタイミングを、`audio_paths`取得後、かつキューへの追加が成功した後に変更
- または、`queued_chunks > 0`の場合のみフラグをセット

### 2. エラーハンドリングの強化
- `audio_paths`取得時のエラーログを追加
- キューへの追加時のエラーログを追加

### 3. ログの追加
- `audio_paths`取得前後のログを追加
- キューへの追加前後のログを追加

### 4. フラグのリセット
- エラーが発生した場合、フラグをリセットして再試行できるようにする

---

## 【7. 結論】

### 修正の効果
- ✅ `[INIT_SEQ]`ログ: 正常に出力されている
- ✅ フラグのセット: 正常に動作している
- ❌ 初期音声シーケンスの処理: ログが見つからない（処理が中断されている可能性）

### 新たに発見された問題
1. **フラグセットのタイミングが早すぎる**
   - フラグが`audio_paths`取得の前にセットされている
   - そのため、処理が中断されてもフラグはセットされたまま

2. **初期音声シーケンスの処理ログが見つからない**
   - `audio_paths`取得やキューへの追加のログが見つからない
   - 処理が中断されている可能性

### 次のステップ
1. フラグセットのタイミングを変更（`audio_paths`取得後、かつキューへの追加が成功した後）
2. エラーハンドリングの強化
3. ログの追加（`audio_paths`取得前後、キューへの追加前後）

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 19:55

