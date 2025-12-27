# 最新通話ログ調査報告書（ASRスキップ問題）

**調査日時**: 2025-12-27 20:38頃  
**対象通話ID**: `in-2025122720363473`  
**報告された問題**: 初回アナウンスあり、反応なし、催促アナウンスあり

---

## 【1. 通話開始時の状況】

### 通話開始フロー

1. **20:36:34.818**: `[FS_RTP_MONITOR] Mapped call_id=in-2025122720363473`
2. **20:36:55.837**: `[FS_RTP_MONITOR] AICore.enable_asr() called successfully`
3. **20:36:56.006**: `[REQUEST_GEN] Generator started for call_id=in-2025122720363473`
4. **20:37:51.008**: `[RTP_RECOVERY] [LOC_01]` - 自動登録
5. **20:37:51.009**: `[RTP_AUDIO_RMS] rms=1` - 最初のRTPパケット受信
6. **20:37:51.011**: `[ASR_SKIP] call_id=in-2025122720363473 already ended, skipping on_new_audio` - **重要：最初の音声パケットでスキップ**
7. **20:37:51.077**: `[INIT_METHOD_ENTRY] Called with client_id=000` - **初期アナウンス処理開始**
8. **20:37:51.078**: `[INIT_DEBUG] Calling play_incoming_sequence for client=000` - **初期アナウンス処理実行中**
9. **20:37:51.085**: `[ASR_REQ_ALIVE] Yielding audio packet #1` - **ASRへの音声送信開始**

### 初期アナウンス処理の状況

**確認できたログ**:
- ✅ `[INIT_TASK_START] Created task for 000` - タスク生成ログ
- ✅ `[INIT_METHOD_ENTRY] Called with client_id=000` - 関数エントリーログ
- ✅ `[INIT_DEBUG] Calling play_incoming_sequence for client=000` - 初期アナウンス処理開始

**見つからないログ**:
- ❌ `[INIT_DEBUG] audio_paths result: ...` - audio_paths取得結果のログ
- ❌ `[INIT_SEQ] Flag set for ... Queued ... chunks.` - キュー追加成功後のログ
- ❌ `[client=000] initial greeting enqueued` - 初期アナウンスキュー追加ログ

**観察**:
- 初期アナウンス処理は開始されているが、完了ログが見つからない
- `play_incoming_sequence`呼び出し後のログが見つからない

---

## 【2. ASRへの音声送信状況】

### ASRリクエスト送信の確認

**確認できたログ**:
- ✅ `[ASR_REQ_ALIVE] Yielding audio packet #1` - 最初のパケット
- ✅ `[ASR_REQ_ALIVE] Yielding audio packet #250` - 250パケット目
- ✅ `[ASR_REQ_ALIVE] Yielding audio packet #1700` - 1700パケット目（大量に送信されている）

**観察**:
- ASRへの音声送信は正常に動作している
- 大量のパケットが送信されている（1700パケット以上）

### 重要な問題：最初の音声パケットでスキップ

**20:37:51.011**: `[ASR_SKIP] call_id=in-2025122720363473 already ended, skipping on_new_audio`

**観察**:
- 最初の音声パケット（`on_new_audio`）で「already ended」と判定されている
- しかし、その後の音声パケットは正常に処理されている
- **最初の音声パケットがスキップされた可能性**

---

## 【3. ASRレスポンスの確認】

### ASRレスポンスログの検索結果

**見つからないログ**:
- ❌ `[ASR_RAW_RES]`ログが見つからない
- ❌ `[ASR_TRANSCRIPT]`ログが見つからない
- ❌ `[ASR_GOOGLE_RAW]`ログが見つからない

**観察**:
- ASRへの音声送信は正常（1700パケット以上）
- しかし、ASRからのレスポンスが来ていない
- Google Speech-to-Text APIからのレスポンスが来ていない可能性

---

## 【4. RMS値の変化】

### RMS値の確認

**20:37:51.009-20:37:51.289**:
- `rms=0-2` (無音から低い値)
- `max_amplitude=8-10` (非常に低い)
- `first_5_samples=(0, 0, 0, 0, 0)` (すべてゼロ)

**観察**:
- RMS値は低い（0-2程度）ので、音声は検出されていない（無音）
- サンプル値もすべてゼロなので、実質的な無音状態

---

## 【5. 現在のアクティブな通話本数】

### ログからの確認

**最新の`_active_calls`操作**:
- **20:31:57.997**: `[CALL_END_TRACE] [LOC_02] Discarding call_id=in-2025122720302954 from _active_calls`
- **現在のアクティブな通話**: **0本**（通話は終了している）

---

## 【6. 問題の原因分析】

### 可能性のある原因

1. **最初の音声パケットでスキップ**
   - `[ASR_SKIP] call_id=in-2025122720363473 already ended, skipping on_new_audio`
   - 最初の音声パケットがスキップされたため、ASRストリームが正しく開始されていない可能性
   - しかし、その後の音声パケットは正常に処理されている

2. **ASRレスポンスが来ていない**
   - `[ASR_RAW_RES]`ログが見つからない
   - Google Speech-to-Text APIからのレスポンスが来ていない可能性
   - または、レスポンスは来ているが、ログが出力されていない可能性

3. **RMS値が低い（無音）**
   - RMS値は0-2程度で、実質的な無音状態
   - 音声が検出されていないため、ASRが反応しない可能性

4. **初期アナウンス処理が完了していない**
   - `[INIT_DEBUG] Calling play_incoming_sequence`ログは出力されている
   - しかし、その後のログ（`audio_paths result`、`Flag set`など）が見つからない
   - 初期アナウンス処理が途中で中断している可能性

---

## 【7. 推奨事項】

### 1. `[ASR_SKIP]`の原因確認
- `already ended`と判定される理由を確認
- 最初の音声パケットがスキップされないように修正

### 2. ASRレスポンスの確認
- Google Speech-to-Text APIからのレスポンスが来ているか確認
- `[ASR_RAW_RES]`ログが出力されていない理由を確認

### 3. 初期アナウンス処理の完了確認
- `play_incoming_sequence`呼び出し後のログを確認
- 初期アナウンス処理が完了しているか確認

### 4. RMS値の確認
- 音声が検出されているか確認
- マイクや音声入力の設定を確認

---

## 【8. 結論】

### 修正の効果
- ✅ 初期アナウンス処理は開始されている（`[INIT_TASK_START]`、`[INIT_METHOD_ENTRY]`、`[INIT_DEBUG]`）
- ✅ ASRへの音声送信は正常（`[ASR_REQ_ALIVE]`が大量に出力されている）
- ❌ しかし、最初の音声パケットで`[ASR_SKIP]`が発生している
- ❌ ASRからのレスポンスが来ていない（`[ASR_RAW_RES]`ログが見つからない）
- ❌ 初期アナウンス処理の完了ログが見つからない

### 新たに発見された問題
1. **最初の音声パケットでスキップ**
   - `[ASR_SKIP] call_id=in-2025122720363473 already ended, skipping on_new_audio`
   - 最初の音声パケットがスキップされたため、ASRストリームが正しく開始されていない可能性

2. **ASRレスポンスが来ていない**
   - `[ASR_RAW_RES]`ログが見つからない
   - Google Speech-to-Text APIからのレスポンスが来ていない可能性

3. **初期アナウンス処理が完了していない**
   - `[INIT_DEBUG] Calling play_incoming_sequence`ログは出力されている
   - しかし、その後のログが見つからない

### 次のステップ
1. `[ASR_SKIP]`の原因確認（`already ended`と判定される理由）
2. ASRレスポンスの確認（Google Speech-to-Text APIからのレスポンス）
3. 初期アナウンス処理の完了確認（`play_incoming_sequence`呼び出し後のログ）

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 20:38

