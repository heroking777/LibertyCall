# 最新通話レポート: ASR反応なし問題

## 通話情報
- **通話ID**: `in-2025122721280912`
- **開始時刻**: 2025-12-27 21:28:09
- **終了時刻**: 2025-12-27 21:28:41
- **通話時間**: 約32秒
- **クライアントID**: `000`

## 観察された動作
1. ✅ **初回アナウンスあり**: 初期アナウンスは正常に再生された
2. ❌ **ASR反応なし**: ASRからのレスポンスが一切受信されなかった
3. ✅ **催促アナウンスあり**: 催促アナウンスは正常に再生された

## ログ分析結果

### 1. 初期アナウンス処理
```
2025-12-27 21:28:09,862 [WARNING] [INIT_SEQ] Flag set for in-2025122721280912. Queued 25 chunks.
2025-12-27 21:28:11,985 [WARNING] [INIT_SEQ] Skipping initial sequence for in-2025122721280912 (already played).
```
- ✅ 初期アナウンスは正常にキューに追加され、再生された
- 25チャンクがキューに追加された

### 2. ASRストリーム処理

#### 2.1 音声データの受信
- ✅ 音声データは正常に受信されている
- `[ASR_DEBUG] Calling on_new_audio` ログが多数出力されている
- `STREAMING_FEED` ログも正常に出力されている（例: `idx=1480 dt=19.8ms call_id=in-2025122721280912 len=640 rms=6`）

#### 2.2 GoogleASRストリームワーカーの状態
- ❌ **重要**: 最新の通話（`in-2025122721280912`）では、`[ASR_FOR_LOOP]`ログが**一切出力されていない**
- ❌ `STREAM_WORKER_LOOP_START` や `STREAM_WORKER_ENTRY` のログも見当たらない
- ❌ `GoogleASR: QUEUE_PUT` や `GoogleASR: STREAMING_FEED` のログも見当たらない

#### 2.3 比較: 別の通話（正常動作）
別の通話（`in-2025122721273935`）では以下のログが正常に出力されている：
```
2025-12-27 21:28:04,406 [WARNING] GoogleASR: [ASR_FOR_LOOP] Got response from Google ASR
2025-12-27 21:28:04,406 [WARNING] GoogleASR: [ASR_RAW_RES] Response received. results=1 error_code=0
2025-12-27 21:28:04,334 [INFO] GoogleASR: GoogleASR: QUEUE_PUT: call_id=in-2025122721273935 len=640 bytes
```

### 3. エラーログ
```
2025-12-27 21:28:08,926 [ERROR] GoogleASR: [ASR_EXCEPTION_TYPE] Exception type: Unknown
2025-12-27 21:28:08,927 [ERROR] GoogleASR: [ASR_EXCEPTION_STR] Exception str: None Exception iterating requests!
2025-12-27 21:28:08,927 [ERROR] GoogleASR: [ASR_EXCEPTION_REPR] Exception repr: Unknown('Exception iterating requests!')
2025-12-27 21:28:08,927 [ERROR] GoogleASR: [ASR_EXCEPTION_ARGS] Exception args: ('Exception iterating requests!',)
2025-12-27 21:28:08,927 [WARNING] GoogleASR: GoogleASR: STREAM_WORKER_CRASHED (will restart on next feed_audio)
```
- ⚠️ **注意**: このエラーは21:28:08に発生しており、最新の通話（21:28:09開始）より**前**である
- このエラーは別の通話で発生した可能性が高い

### 4. 通話終了処理
```
2025-12-27 21:28:41,610 [INFO] [AICORE] on_call_end() call_id=in-2025122721280912
2025-12-27 21:28:41,611 [WARNING] [EVENT_SOCKET_DONE] Removed in-2025122721280912 from active_calls (finally block)
2025-12-27 21:28:41,994 [INFO] [ASRHandler] All reminders played, no response. Hanging up in-2025122721280912
```
- ✅ 通話終了処理は正常に実行された
- ✅ `_active_calls`からの削除も正常に実行された

## 問題の根本原因（推測）

### 主要な問題
**最新の通話（`in-2025122721280912`）では、GoogleASRストリームワーカーが起動していない、または`for response in responses:`ループに到達していない可能性が高い。**

### 具体的な問題点
1. **ASRストリームが開始されていない**
   - `feed_audio()` が呼ばれていない、または呼ばれてもストリームが開始されていない
   - `start_stream()` が呼ばれていない可能性

2. **音声データがGoogleASRに到達していない**
   - `on_new_audio()` は呼ばれているが、GoogleASRのキューに到達していない
   - `GoogleASR: QUEUE_PUT` ログが出力されていない

3. **ストリームワーカーがクラッシュしている**
   - 前の通話（21:28:08）でエラーが発生し、ストリームワーカーがクラッシュ
   - 次の通話（21:28:09）開始時にストリームワーカーが再起動されていない

## 確認が必要な項目

1. **`feed_audio()` の呼び出し確認**
   - `on_new_audio()` から `feed_audio()` が呼ばれているか
   - `feed_audio()` 内でストリームが開始されているか

2. **ストリームワーカーの再起動メカニズム**
   - エラー発生後の自動再起動が機能しているか
   - `will restart on next feed_audio` の実装が正しく動作しているか

3. **GoogleASRインスタンスの状態**
   - 通話開始時にGoogleASRインスタンスが正しく初期化されているか
   - 前の通話のエラーが次の通話に影響していないか

## 次のステップ

1. `on_new_audio()` から `feed_audio()` への呼び出しチェーンを確認
2. `feed_audio()` 内でストリームが開始されているかを確認
3. ストリームワーカーの再起動メカニズムを確認
4. GoogleASRインスタンスのライフサイクル管理を確認

