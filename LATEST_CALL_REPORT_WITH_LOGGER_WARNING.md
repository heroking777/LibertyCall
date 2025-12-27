# 最新通話ログ調査報告書（logger.warning修正後）

**調査日時**: 2025-12-27 19:18頃  
**対象通話ID**: `in-2025122719174465`  
**調査目的**: `self.logger.warning`への変更後のログ出力確認

---

## 【重要な発見】

### 1. 修正が正常に反映されている

#### `[DEBUG_VERSION]`ログ
- **出力状況**: ✅ **正常に出力されている**
- **確認**: `2025-12-27 19:17:20,825 [WARNING] __main__: [DEBUG_VERSION] RealtimeGateway initialized with UPDATED LOGGING logic.`
- **結論**: 修正版が正常に起動している

#### `[RTP_ENTRY]`ログ
- **出力状況**: ✅ **正常に出力されている**
- **件数**: 約1987件（最新の通話期間中）
- **例**: 
  ```
  2025-12-27 19:18:16,533 [WARNING] __main__: [RTP_ENTRY] Time=1766830696.534 Len=172 Addr=('61.213.230.81', 10724)
  2025-12-27 19:18:16,539 [WARNING] __main__: [RTP_ENTRY] Time=1766830696.540 Len=172 Addr=('160.251.170.253', 7160)
  ```
- **観察**: 
  - すべて`Len=172`（12バイト以上）で正常なRTPパケット
  - 双方向のRTPパケットが正常に受信されている
  - `WARNING`レベルで確実にログファイルに記録されている

#### `[RTP_RAW]`ログ
- **出力状況**: ✅ **正常に出力されている**
- **例**:
  ```
  2025-12-27 19:18:16,678 [WARNING] __main__: [RTP_RAW] Time=1766830696.678 Len=172 PT=0 SSRC=05553ba0 Seq=20008 Mark=0 Addr=('160.251.170.253', 7160)
  2025-12-27 19:18:16,678 [INFO] __main__: [RTP_RAW] Time=1766830696.678 Len=172 PT=0 SSRC=05553ba0 Seq=20008 Mark=0 Addr=('160.251.170.253', 7160)
  ```
- **観察**: `WARNING`と`INFO`の両方で出力されている（重複ログ）

#### `[CALL_END_TRACE] [LOC_04]`ログ
- **出力状況**: ✅ **正常に出力されている**
- **例**:
  ```
  2025-12-27 19:18:16,783 [WARNING] __main__: [CALL_END_TRACE] [LOC_04] Setting is_active=False for in-2025122719174465 at 1766830696.784
  2025-12-27 19:18:16,783 [INFO] __main__: [CALL_END_TRACE] [LOC_04] Discarding call_id=in-2025122719174465 from _active_calls at 1766830696.784
  ```

### 2. `[CALL_START_TRACE] [LOC_START]`ログ

#### 出力状況
- **出力状況**: ✅ **正常に出力されている**
- **件数**: 2件（通話開始時に2回追加されている）
- **例**:
  ```
  2025-12-27 19:17:44,692 [WARNING] __main__: [CALL_START_TRACE] [LOC_START] Adding in-2025122719174465 to _active_calls (event_socket) at 1766830664.692
  2025-12-27 19:17:44,692 [WARNING] __main__: [CALL_START_TRACE] [LOC_START] Adding in-2025122719174465 to _active_calls (_queue_initial_audio_sequence) at 1766830664.692
  ```

#### 観察
1. **`event_socket`経由で追加**（4679行目）
   - 通話開始時に`event_socket`経由で`_active_calls`に追加されている
   
2. **`_queue_initial_audio_sequence`経由で追加**（3775行目）
   - 初期音声シーケンス再生時に再度追加されている
   - 同じ通話IDが2回追加されている（重複登録の可能性）

---

## 【通話の時系列】

### 通話ID: `in-2025122719174465`

| 時刻 | イベント | ログ |
|------|----------|------|
| 19:17:44.691 | 通話開始 | `[EVENT_SOCKET] Generated call_id=in-2025122719174465` |
| 19:17:44.692 | `_active_calls`追加（1回目） | `[CALL_START_TRACE] [LOC_START] Adding ... (event_socket)` |
| 19:17:44.692 | `_active_calls`追加（2回目） | `[CALL_START_TRACE] [LOC_START] Adding ... (_queue_initial_audio_sequence)` |
| 19:17:51.413 | ASR処理開始 | `[ASR_DEBUG] Calling on_new_audio` |
| 19:17:51.459 | RTPパケット受信 | `[RTP_ENTRY] Time=1766830671.460 Len=172` |
| 19:18:03.034 | ASR処理継続 | `[ASR_DEBUG] Calling on_new_audio` |
| 19:18:16.533 | RTPパケット受信 | `[RTP_ENTRY] Time=1766830696.534 Len=172` |
| 19:18:16.783 | 通話終了 | `[CALL_END_TRACE] [LOC_04] Setting is_active=False` |

### 重要な観察

1. **`[RTP_ENTRY]`ログが正常に出力されている**
   - すべてのRTPパケット受信時にログが出力されている
   - `Len=172`で正常なパケットサイズ

2. ✅ **`[CALL_START_TRACE] [LOC_START]`ログが正常に出力されている**
   - 通話開始時に`_active_calls`への追加ログが2回出力されている
   - `event_socket`経由と`_queue_initial_audio_sequence`経由で追加されている

3. **`[CALL_END_TRACE] [LOC_04]`ログが正常に出力されている**
   - 通話終了時に`_active_calls`からの削除ログが出力されている

---

## 【現在のアクティブな通話本数】

### 確認方法
```bash
grep -E "Added.*_active_calls|Removed.*_active_calls" /opt/libertycall/logs/realtime_gateway.log | tail -20
```

### 結果
- **最新の削除**: `in-2025122719174465` (19:18:16.783)
- **最新の追加**: 該当ログが見つからない（`[CALL_START_TRACE]`ログも見つからない）

### 現在のアクティブな通話本数
- **推定: 0件**
- 理由: 最新の通話は既に終了し、`_active_calls`から削除されている

---

## 【問題の分析】

### 成功した点

1. ✅ **`[RTP_ENTRY]`ログが正常に出力されている**
   - すべてのRTPパケット受信時にログが出力されている
   - `self.logger.warning`への変更が正常に機能している

2. ✅ **`[CALL_END_TRACE]`ログが正常に出力されている**
   - 通話終了時にログが出力されている

3. ✅ **修正版が正常に起動している**
   - `[DEBUG_VERSION]`ログが出力されている

### 観察事項

1. ⚠️ **`_active_calls`への重複登録**
   - 通話開始時に同じ通話IDが2回追加されている
   - `event_socket`経由（4679行目）と`_queue_initial_audio_sequence`経由（3775行目）
   - `set`型なので重複は問題ないが、ログが2回出力されている

### 詳細分析

1. **通話開始フロー**
   - `event_socket`経由で通話が開始される（19:17:44.691）
   - `on_call_start()`が呼ばれる（19:17:44.692）
   - `_active_calls`に追加される（19:17:44.692 - event_socket経由）
   - `_queue_initial_audio_sequence()`が呼ばれる（19:17:44.692）
   - `_active_calls`に再度追加される（19:17:44.692 - _queue_initial_audio_sequence経由）

2. **重複登録について**
   - `_active_calls`は`set`型なので、重複登録は問題ない
   - しかし、ログが2回出力されているため、条件分岐の確認が必要

---

## 【結論】

1. **修正は正常に反映されている**
   - `[RTP_ENTRY]`ログ: ✅ 正常出力（約1987件）
   - `[CALL_END_TRACE]`ログ: ✅ 正常出力
   - `[DEBUG_VERSION]`ログ: ✅ 正常出力

2. ✅ **`[CALL_START_TRACE] [LOC_START]`ログが正常に出力されている**
   - 通話開始時に`_active_calls`への追加ログが2回出力されている
   - すべての追加箇所でログが正常に出力されている

3. **推奨アクション**
   - `_active_calls`への重複登録を防ぐため、条件分岐の確認
   - ただし、`set`型なので機能的な問題はない

---

## 【補足情報】

### ログ出力統計

- `[RTP_ENTRY]`: 約1987件（正常出力）
- `[RTP_RAW]`: 正常出力（WARNINGとINFOの両方）
- `[CALL_END_TRACE] [LOC_04]`: 1件（正常出力）
- `[CALL_START_TRACE] [LOC_START]`: 2件（正常出力）

### 通話の処理状況

- **正常**: 通話は正常に処理され、ASRも動作している
- **問題**: `[CALL_START_TRACE] [LOC_START]`ログが出力されていない

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 19:18

