# LibertyCall ASR 頭切れ問題の分析と修正案

## 問題の概要

通話開始直後の「もしもし」「あのー」「人間と変わって」が頭切れする現象が継続している。

## 特定された問題箇所

### 1. ASR（GoogleASR）起動タイミングの問題

**問題点:**
- `feed_audio`内で`_start_stream_worker`を呼んでいるが、スレッド起動に時間がかかる
- 最初の1〜2語がキューに入る前にストリームが開始されていない可能性
- スレッド起動 → Google API接続 → ストリーム開始までに100〜200msの遅延が発生

**現在のコード:**
```python
def feed_audio(self, call_id: str, pcm16k_bytes: bytes) -> None:
    # 常に最初に _start_stream_worker() を呼ぶ
    self._start_stream_worker(call_id)
    # その後に self._q.put(pcm16k_bytes)
    self._q.put(pcm16k_bytes)
```

**修正案:**
- 通話開始時（RTP受信開始時）に事前にストリームを起動
- 初回シーケンス再生中でもストリームを起動し、音声をバッファリング

### 2. RTP → PCM の流れの処理遅延

**問題点:**
- RTP_RECV → STREAMING_FEED → STREAMING_ON_NEW_AUDIO → GoogleASR.feed_audio の4段階で40〜70msの遅延
- `decode_ulaw`、`resample_poly`、`queue.put`が同期的に実行されている
- `queue.put`がブロッキングで、キューが満杯の場合に遅延が発生

**修正案:**
- `queue.put`をノンブロッキング化（`put_nowait`使用、キュー満杯時は警告してスキップ）
- キューサイズを増加（200 → 500）
- 処理時間を計測してログ出力

### 3. GoogleASR の audio timeout の根本原因

**問題点:**
- `request_generator_from_queue`で`timeout=0.5`秒で待機
- 音声が来ないと`continue`して空のチャンクを送らない
- Google側は音声が来ないと「Long duration elapsed without audio」エラーを返す

**現在のコード:**
```python
chunk = self._q.get(timeout=0.5)
except queue.Empty:
    if self._stop_event.is_set():
        break
    continue  # 空のチャンクを送らない
```

**修正案:**
- 音声が来ない場合でも定期的に空のチャンクを送る（Google側のタイムアウトを防ぐ）
- または、timeoutを短くして（0.1秒）、空のチャンクを送る頻度を増やす

### 4. 初回シーケンス再生中のASRブロック問題

**問題点:**
- `initial_sequence_playing`がTrueの間はASRを完全にスキップ
- 初回シーケンス再生中にユーザーが話し始めると、その音声が失われる

**現在のコード:**
```python
if self.streaming_enabled:
    if self.initial_sequence_playing:
        return  # ASRを完全にスキップ
```

**修正案:**
- 初回シーケンス再生中でもASRストリームを起動
- 音声をバッファリングして、シーケンス再生完了後に送信
- または、シーケンス再生中でもASRを有効化（TTSと同時にASRを実行）

### 5. ASR_ERROR_FALLBACK の動作確認

**現在のコード:**
```python
def _on_asr_error(self, call_id: str, error: Exception) -> None:
    # エラーハンドラ
    if self._error_callback is not None:
        self._error_callback(call_id, e)
```

**確認事項:**
- `_stream_worker`の例外発生 → `error_callback` → `_on_asr_error` → `tts_callback` の流れが正しいか
- `tts_callback`が正しく設定されているか

## 修正コードの提案

### 修正1: ASR起動タイミングの改善

**ai_core.py:**
- `feed_audio`内でストリームを事前起動
- 初回チャンクをバッファリングして、ストリーム起動後に送信

### 修正2: キューサイズとノンブロッキング化

**ai_core.py:**
- キューサイズを200 → 500に増加
- `queue.put`を`put_nowait`に変更（キュー満杯時は警告してスキップ）

### 修正3: GoogleASRのtimeout処理改善

**ai_core.py:**
- 音声が来ない場合でも定期的に空のチャンクを送る
- timeoutを0.1秒に短縮

### 修正4: 初回シーケンス再生中のバッファリング

**realtime_gateway.py:**
- 初回シーケンス再生中でもASRストリームを起動
- 音声をバッファリングして、シーケンス再生完了後に送信

## 最終的な最適化案

1. **通話開始時にストリームを事前起動**
   - RTP受信開始時に`_start_stream_worker`を呼び出す
   - 初回シーケンス再生中でもストリームを起動

2. **最初の100〜300msの音声をバッファリング**
   - ストリーム起動までの音声をバッファリング
   - ストリーム起動後にバッファを送信

3. **queue.putのノンブロッキング化**
   - `put_nowait`を使用してブロッキングを防ぐ
   - キュー満杯時は警告してスキップ（音声ロスを最小化）

4. **GoogleASRのtimeout処理改善**
   - 音声が来ない場合でも定期的に空のチャンクを送る
   - Google側のタイムアウトを防ぐ

5. **初回シーケンス再生中のASR有効化**
   - シーケンス再生中でもASRを有効化
   - 音声をバッファリングして、シーケンス再生完了後に送信

