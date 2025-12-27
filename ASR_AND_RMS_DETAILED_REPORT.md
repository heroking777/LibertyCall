# ASR音声品質と_active_calls重複登録詳細調査報告書

**調査日時**: 2025-12-27 19:20頃  
**対象通話ID**: `in-2025122719174465`  
**調査目的**: 
1. RMS値の推移と音声品質の確認
2. ASR結果の確認
3. `_active_calls`重複登録の原因特定

---

## 【1. RMS値の確認結果】

### RMS値の統計

#### 全体統計
- **総ログ数**: 385件
- **RMS値の分布**:
  - `rms=1`: 57件
  - `rms=2`: 158件（最多）
  - `rms=3`: 32件
  - `rms=4`: 8件
  - `rms=5`: 9件
  - `rms=6`: 9件
  - `rms=7`: 15件
  - `rms=8`: 5件
  - `rms=9`: 4件
  - `rms=10`: 3件
  - その他: 異常値（1000以上）が数件

#### ASR有効化後（19:17:51以降）のRMS値

**観察結果**:
- **大部分が`rms=1`または`rms=2`**（無音に近い状態）
- **例**:
  ```
  19:17:51.156: rms=2 (16khz_resample)
  19:17:51.194: rms=2 (ulaw_decode)
  19:17:51.354: rms=0 (16khz_resample) ← 完全無音
  19:17:51.393: rms=2 (ulaw_decode)
  19:17:51.554: rms=2 (16khz_resample)
  19:17:51.593: rms=2 (ulaw_decode)
  ```

#### 問題点

1. **RMS値が極めて低い**
   - 大部分が`rms=1`または`rms=2`
   - これは**無音に近い状態**を示している
   - 正常な音声では`rms=10`以上が期待される

2. **異常値の存在**
   - `rms=9335`, `rms=9022`, `rms=7950`などの異常に高い値が数件存在
   - これらはノイズやパケットエラーの可能性

3. **音声品質の問題**
   - ASR有効化後も音声レベルが低いまま
   - 実際の音声がASRに届いていない可能性

---

## 【2. ASR結果の確認結果】

### ASR_TRANSCRIPTログ
- **結果**: **該当ログが見つからない**
- **確認コマンド**: 
  ```bash
  grep "in-2025122719174465" /opt/libertycall/logs/realtime_gateway.log | grep "ASR_TRANSCRIPT"
  ```
- **確認範囲**: `realtime_gateway.log`のみ

### ASR_GOOGLE_RAWログ
- **結果**: **該当ログが見つからない**
- **確認コマンド**: 
  ```bash
  grep "in-2025122719174465" /opt/libertycall/logs/realtime_gateway.log | grep "ASR_GOOGLE_RAW"
  ```
- **確認範囲**: `realtime_gateway.log`のみ

### ASR処理の実行状況

**確認結果**:
- `[ASR_DEBUG] Calling on_new_audio`: 多数出力されている
- `[STREAMING_FEED]`: 正常に出力されている
- `GoogleASR: QUEUE_PUT`: 正常に出力されている
- **ASRハンドラーは正常に動作している**

**ASR結果のログ出力場所**:
- `ASR_TRANSCRIPT`や`ASR_GOOGLE_RAW`ログは、別のログファイル（`gateway_stderr.log`など）に出力されている可能性
- または、ASR結果が返されていない（無音と判断されている）可能性

### 観察

1. **ASR結果が出力されていない**
   - `ASR_TRANSCRIPT`ログが見つからない
   - `ASR_GOOGLE_RAW`ログも見つからない
   - これは、ASRが音声を認識できていない、または結果が返されていないことを示している

2. **ASR処理は実行されている**
   - `[ASR_DEBUG] Calling on_new_audio`ログは多数出力されている
   - `[STREAMING_FEED]`ログも出力されている
   - しかし、認識結果が返されていない

3. **可能性**
   - RMS値が低すぎてASRが無音と判断している
   - 音声データがASRに正しく渡されていない
   - ASRの設定やAPI接続に問題がある

---

## 【3. _active_calls重複登録の原因特定】

### `_active_calls.add()`の実行箇所

コード内で`_active_calls.add()`が実行される箇所は**4箇所**あります：

#### 1. `handle_rtp_packet`メソッド内（2117行目）
```python
# 最初のRTPパケット受信時に _active_calls に登録（確実なタイミング）
if effective_call_id and effective_call_id not in self._active_calls:
    self.logger.warning(f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls at {time.time():.3f}")
    self._active_calls.add(effective_call_id)  # ← 2117行目
```
- **条件**: `effective_call_id`が存在し、かつ`_active_calls`に存在しない場合
- **実行タイミング**: 最初のRTPパケット受信時

#### 2. `handle_rtp_packet`メソッド内（2144行目）
```python
# フォールバック: _active_calls が空で、effective_call_id が取得できない場合でも強制登録
if not self._active_calls:
    # ...
    self._active_calls.add(effective_call_id)  # ← 2144行目
```
- **条件**: `_active_calls`が空の場合
- **実行タイミング**: フォールバック処理時

#### 3. `_queue_initial_audio_sequence`メソッド内（3776行目）
```python
def _queue_initial_audio_sequence(self, client_id: Optional[str]) -> None:
    # ...
    if effective_call_id:
        # ...
        # アクティブな通話として登録
        self.logger.warning(f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls (_queue_initial_audio_sequence) at {time.time():.3f}")
        self._active_calls.add(effective_call_id)  # ← 3776行目
```
- **条件**: `effective_call_id`が存在する場合
- **実行タイミング**: 初期音声シーケンス再生時
- **問題**: **条件分岐がない**（`if effective_call_id not in self._active_calls:`がない）

#### 4. `event_socket`処理内（4680行目）
```python
if event_type == 'call_start':
    # ...
    # RealtimeGateway側の状態を更新
    self.logger.warning(f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls (event_socket) at {time.time():.3f}")
    self._active_calls.add(effective_call_id)  # ← 4680行目
    # ...
    # 初回アナウンス再生処理を実行
    self._queue_initial_audio_sequence(client_id)  # ← 4687行目で呼び出し
```
- **条件**: `event_type == 'call_start'`の場合
- **実行タイミング**: 通話開始イベント受信時
- **問題**: この後に`_queue_initial_audio_sequence()`が呼ばれ、再度追加される

### 重複登録の原因

**原因**: `event_socket`処理（4680行目）と`_queue_initial_audio_sequence`（3776行目）の2箇所で追加されている

**フロー**:
1. `event_socket`で`call_start`イベントを受信（19:17:44.691）
2. `_active_calls.add()`を実行（4680行目）- **1回目**
3. `_queue_initial_audio_sequence()`を呼び出し（4687行目）
4. `_queue_initial_audio_sequence()`内で再度`_active_calls.add()`を実行（3776行目）- **2回目**

**問題点**:
- `_queue_initial_audio_sequence()`内（3776行目）に条件分岐`if effective_call_id not in self._active_calls:`がない
- そのため、既に`_active_calls`に存在していても再度追加しようとする（ただし`set`型なので実際には重複しない）

---

## 【結論と推奨事項】

### 1. RMS値の問題

**問題**: RMS値が極めて低い（大部分が`rms=1`または`rms=2`）

**推奨事項**:
- 音声入力レベルの確認
- マイクの設定やゲイン調整
- RTPパケットの音声データが正しくデコードされているか確認

### 2. ASR結果が出力されない問題

**問題**: ASR結果（`ASR_TRANSCRIPT`、`ASR_GOOGLE_RAW`）が出力されていない

**推奨事項**:
- ASR APIの接続状態を確認
- ASR設定（言語、サンプルレート等）を確認
- RMS値が低すぎてASRが無音と判断している可能性を調査

### 3. _active_calls重複登録の問題

**問題**: 通話開始時に`_active_calls`に2回追加されている

**原因**: 
- `event_socket`処理（4680行目）で1回追加
- `_queue_initial_audio_sequence`（3776行目）で再度追加

**推奨事項**:
- `_queue_initial_audio_sequence`内（3776行目）に条件分岐を追加：
  ```python
  if effective_call_id and effective_call_id not in self._active_calls:
      self.logger.warning(f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls (_queue_initial_audio_sequence) at {time.time():.3f}")
      self._active_calls.add(effective_call_id)
  ```
- または、`event_socket`処理で既に追加済みの場合は`_queue_initial_audio_sequence`内での追加をスキップ

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 19:20

