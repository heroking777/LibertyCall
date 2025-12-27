# 最新通話ログ分析レポート（v1p1beta1 API統一後）

## 通話情報
- **通話ID**: `in-2025122723004247`
- **開始時刻**: 2025-12-27 23:00:42
- **終了時刻**: 2025-12-27 23:01:14（約30秒）
- **ユーザー報告**:
  - ✅ 初回アナウンス: あり
  - ❌ ASR反応: なし
  - ✅ 催促アナウンス: あり

---

## 1. 音声受信状況

### ✅ 正常
- RTPパケット受信: 正常（`[RTP_RECV_RAW]`、`[RTP_ENTRY]`）
- 音声データ処理: 正常（`[ASR_DEBUG] Calling on_new_audio with 640 bytes`）
- RMS値: 高い（`rms=5468`、`rms=5327`など）
- `feed_audio`呼び出し: 正常（`[ON_NEW_AUDIO_FEED]`、`[ON_NEW_AUDIO_FEED_DONE]`）

**結論**: 音声受信は正常に動作している

---

## 2. ASR処理状況

### ❌ 問題点

#### 2.1 GoogleStreamingASRのログが存在しない
- `[GOOGLE_ASR_STREAM]`、`[ASR_STREAM_START]`、`[ASR_STREAM_ITER]`などのログが**一切出力されていない**
- `streaming_recognize`呼び出しのログがない
- Google ASRからの応答ログがない

#### 2.2 ASRHandlerのログ
- `[ASRHandler] Reminder file not found` は出力されている
- しかし、`GoogleStreamingASR`の初期化やストリーミング開始のログがない

#### 2.3 認識結果
- **ASR認識結果が一切返ってこない**
- `[ASR_TRANSCRIPT]`、`[ASR_RESULT]`などのログがない
- `もしもし`などの音声認識結果がない

**結論**: `GoogleStreamingASR`が実際に動作していない可能性が高い

---

## 3. エラーログ

### 3.1 asyncioエラー（大量発生）
```
2025-12-27 23:00:57,954 [ERROR] asyncio: Task was destroyed but it is pending!
```
- 大量の`asyncio: Task was destroyed but it is pending!`エラー
- タイミング: 23:00:57〜23:00:59、23:01:02、23:01:14
- **影響**: タスクが正常に終了していない可能性

### 3.2 ASR関連のエラー
- **`streaming_recognize`のエラーは見当たらない**
- 以前の`TypeError: missing 1 required positional argument: 'requests'`エラーは**解消されている**

**結論**: API呼び出しのエラーは解消されたが、ASRが動作していない

---

## 4. 再生処理

### ✅ 正常
- 初回アナウンス: `[INITIAL_SEQUENCE] ON: client=000 initial_sequence_playing=True`
- 催促アナウンス: `[ASRHandler] Reminder file not found`（ファイルが見つからないが、処理は実行されている）

**結論**: 再生処理は正常に動作している

---

## 5. 重要な発見

### 5.1 feed_audioは呼ばれているが、GoogleStreamingASRに渡されていない可能性

ログから確認できること:
- `[ON_NEW_AUDIO_FEED] About to call feed_audio` → `ai_core.py`の`feed_audio`は呼ばれている
- しかし、`GoogleStreamingASR.add_audio()`のログがない
- `[GOOGLE_ASR_REQUEST]`、`[ASR_QUEUE_GET]`などのログがない

**推測**: `ai_core.py`の`feed_audio`が`GoogleStreamingASR`に音声データを渡していない可能性

### 5.2 GoogleStreamingASRが使用されていない可能性

- `asr_handler.py`は`GoogleStreamingASR`をインポートしている
- しかし、実際のストリーミング認識処理が開始されていない
- `start_stream()`が呼ばれていない、または呼ばれてもエラーで停止している可能性

---

## 6. 問題の根本原因（推測）

### 6.1 可能性1: asr_handler.pyが使用されていない
- `realtime_gateway.py`が`ai_core.py`の`GoogleASR`を使用している
- `asr_handler.py`の`GoogleStreamingASR`は使用されていない

### 6.2 可能性2: GoogleStreamingASRの初期化エラー
- `start_stream()`が呼ばれても、内部でエラーが発生して停止している
- エラーログが出力されていない（ログレベルが低い可能性）

### 6.3 可能性3: feed_audioの接続が切れている
- `ai_core.py`の`feed_audio`が`GoogleStreamingASR`に接続されていない
- `asr_handler.py`と`ai_core.py`の間で音声データが渡されていない

---

## 7. 確認が必要な事項

1. **`asr_handler.py`が実際に使用されているか**
   - `realtime_gateway.py`が`asr_handler.py`を呼び出しているか
   - `GoogleStreamingASR`のインスタンスが作成されているか

2. **`GoogleStreamingASR.start_stream()`が呼ばれているか**
   - 呼び出しログがない
   - エラーで停止している可能性

3. **`feed_audio`の接続**
   - `ai_core.py`の`feed_audio`が`GoogleStreamingASR.add_audio()`を呼び出しているか
   - 音声データの流れを確認

4. **ログレベル**
   - `GoogleStreamingASR`のログレベルが低く、出力されていない可能性

---

## 8. まとめ

### ✅ 改善された点
- APIバージョン統一（v1p1beta1）により、`streaming_recognize`のエラーは解消された
- 音声受信は正常に動作している
- 再生処理は正常に動作している

### ❌ 残っている問題
- **ASRがテキストを返さない**
- `GoogleStreamingASR`が実際に動作していない可能性
- `feed_audio`と`GoogleStreamingASR`の接続が切れている可能性

### 🔍 次の調査ステップ
1. `asr_handler.py`が実際に使用されているか確認
2. `GoogleStreamingASR.start_stream()`が呼ばれているか確認
3. `feed_audio`と`GoogleStreamingASR.add_audio()`の接続を確認
4. `GoogleStreamingASR`のログレベルを確認

---

**レポート作成日時**: 2025-12-27 23:01:30
**分析対象ログ**: `/opt/libertycall/logs/realtime_gateway.log`

