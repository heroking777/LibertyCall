# 最新通話ログ調査報告書（音声デコード確認ログ追加後）

**調査日時**: 2025-12-27 19:30頃  
**対象通話ID**: `in-2025122719271123`  
**サービス起動時刻**: 2025-12-27 19:27:07 JST  
**修正版確認**: `[DEBUG_VERSION]`ログが出力されている（19:27:11）

---

## 【1. 修正版の確認】

### サービス状態
- **サービス名**: `liberty_gateway.service`
- **状態**: `active (running)`
- **起動時刻**: 2025-12-27 19:27:07 JST
- **プロセスID**: 2178962
- **修正版確認**: `[DEBUG_VERSION] RealtimeGateway initialized with UPDATED LOGGING logic.` が出力されている

### 修正内容の反映状況
- ✅ `[DEBUG_VERSION]`ログ: 出力されている
- ❌ `[AUDIO_DEBUG]`ログ: **出力されていない**
- ❌ `[CALL_START_TRACE]`ログ: **最新通話では出力されていない**

---

## 【2. 最新通話（in-2025122719271123）の状況】

### 通話開始時刻
- **19:27:11.380**: `[FS_RTP_MONITOR] Mapped call_id=in-2025122719271123 -> uuid=6ff5b5d6-d2cb-4bd2-bb59-5fa96fa19634`

### 問題点

#### 1. `_active_calls`への登録が行われていない
- **`[CALL_START_TRACE]`ログ**: 出力されていない
- **`[EVENT_SOCKET] Received event: call_start`ログ**: 出力されていない
- **結果**: 通話開始時に`_active_calls`に追加されていない

#### 2. RTPパケットがスキップされている
- **19:27:13.417以降**: `[RTP_SKIP] [LOC_01] already ended (Active=False)`が大量に出力されている
- **原因**: `_active_calls`に登録されていないため、`handle_rtp_packet`が早期リターンしている

#### 3. `[AUDIO_DEBUG]`ログが出力されない理由
- `handle_rtp_packet`が`[LOC_01]`で早期リターンしているため、デコード処理まで到達していない
- デコード処理は`[LOC_01]`のチェックの後に実行されるため、ログが出力されない

### RTPペイロードの確認
- **19:27:13.417**: `[RTP_PAYLOAD_DEBUG] payload_len=160 first_bytes=ffff7effffff7effffff`
- **19:27:13.436**: `[RTP_PAYLOAD_DEBUG] payload_len=160 first_bytes=ff7effffffffffffffff`
- **19:27:13.456以降**: `[RTP_PAYLOAD_DEBUG] payload_len=160 first_bytes=ffffffffffffffffffff`（無音データ）

**観察**:
- 最初の数パケットは`ff7e`などの値が含まれている（無音に近いが完全な無音ではない）
- その後は`ffffffffffffffffffff`（完全な無音）が続いている

---

## 【3. 前回通話（in-2025122719174465）との比較】

### 前回通話の状況
- **19:17:44.691**: `[EVENT_SOCKET] Received event: call_start`
- **19:17:44.692**: `[CALL_START_TRACE] [LOC_START] Adding in-2025122719174465 to _active_calls (event_socket)`
- **19:17:44.692**: `[CALL_START_TRACE] [LOC_START] Adding in-2025122719174465 to _active_calls (_queue_initial_audio_sequence)`

**問題点**:
- 修正前のログでは、`_queue_initial_audio_sequence`内でも追加ログが出力されている
- これは修正前のコードで、条件分岐がなかったため

### 最新通話との違い
- **前回**: `event_socket`で`call_start`イベントが受信され、`_active_calls`に追加された
- **最新**: `event_socket`で`call_start`イベントが受信されていない（または処理されていない）

---

## 【4. 現在のアクティブな通話本数】

### 確認方法
- Pythonスクリプトでの直接確認は失敗（モジュールインポートエラー）
- ログからの確認が必要

### ログからの確認
- **最新の`_active_calls`追加ログ**: 19:17:44.692（前回通話）
- **最新の`_active_calls`削除ログ**: 19:18:16.783（前回通話）
- **現在のアクティブな通話**: **0本**（最新通話は`_active_calls`に登録されていない）

---

## 【5. 問題の根本原因】

### 主要な問題
1. **`event_socket`で`call_start`イベントが受信されていない**
   - 最新通話では`[EVENT_SOCKET] Received event: call_start`ログが出力されていない
   - そのため、`_active_calls`に追加されていない

2. **`[AUDIO_DEBUG]`ログが出力されない理由**
   - `handle_rtp_packet`が`[LOC_01]`で早期リターンしているため、デコード処理まで到達していない
   - デコード処理は`[LOC_01]`のチェックの後に実行される

3. **RTPパケットがスキップされている**
   - `_active_calls`に登録されていないため、すべてのRTPパケットがスキップされている

### 修正の効果
- ✅ `_queue_initial_audio_sequence`内の重複登録防止: 修正されている（ただし、最新通話では呼ばれていない）
- ❌ `[AUDIO_DEBUG]`ログ: 出力されていない（`handle_rtp_packet`が早期リターンしているため）

---

## 【6. 推奨事項】

### 1. `event_socket`の`call_start`イベント受信の確認
- 最新通話では`event_socket`で`call_start`イベントが受信されていない
- FreeSWITCH側の設定やイベント送信を確認する必要がある

### 2. `[AUDIO_DEBUG]`ログの出力位置の変更
- 現在、`[AUDIO_DEBUG]`ログはデコード処理後に出力される
- しかし、`[LOC_01]`で早期リターンしているため、ログが出力されない
- **推奨**: `[LOC_01]`のチェックの前に`[AUDIO_DEBUG]`ログを出力するか、`[LOC_01]`のチェックを緩和する

### 3. `_active_calls`への登録タイミングの見直し
- `event_socket`で`call_start`イベントが受信されない場合のフォールバック処理を検討
- 最初のRTPパケット受信時に`_active_calls`に追加する処理（2117行目）が機能していない可能性

---

## 【7. 結論】

### 修正の効果
- ✅ `_queue_initial_audio_sequence`内の重複登録防止: 修正されている
- ❌ `[AUDIO_DEBUG]`ログ: 出力されていない（`handle_rtp_packet`が早期リターンしているため）

### 新たに発見された問題
1. **`event_socket`で`call_start`イベントが受信されていない**
   - 最新通話では`_active_calls`に登録されていない
   - そのため、すべてのRTPパケットがスキップされている

2. **`[AUDIO_DEBUG]`ログが出力されない理由**
   - `handle_rtp_packet`が`[LOC_01]`で早期リターンしているため、デコード処理まで到達していない

### 次のステップ
1. `event_socket`の`call_start`イベント受信の確認
2. `[AUDIO_DEBUG]`ログの出力位置の変更（`[LOC_01]`のチェックの前に出力）
3. `_active_calls`への登録タイミングの見直し

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 19:30

