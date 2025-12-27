# 最新通話ログ調査報告書（2回目のテスト）

**調査日時**: 2025-12-27 19:11頃  
**対象通話ID**: `in-2025122719102697`  
**調査目的**: 追加した`[RTP_ENTRY]`と`[CALL_START_TRACE]`ログの確認（2回目）

---

## 【重要な発見】

### 1. 追加したログが依然として全く出力されていない

#### `[RTP_ENTRY]`ログ
- **期待**: `handle_rtp_packet`メソッドの先頭で無条件出力
- **実際**: **0件**（全く出力されていない）
- **コード位置**: `realtime_gateway.py:1909`

#### `[CALL_START_TRACE] [LOC_START]`ログ
- **期待**: `_active_calls.add()`実行時に出力（4箇所）
- **実際**: **0件**（全く出力されていない）
- **コード位置**: 
  - `realtime_gateway.py:2114` (通常登録)
  - `realtime_gateway.py:2140` (フォールバック登録)
  - `realtime_gateway.py:3771` (_queue_initial_audio_sequence)
  - `realtime_gateway.py:4674` (event_socket)

### 2. 通話は正常に処理されている

#### 通話の流れ
- **19:10:26.436**: `on_call_start()`が呼ばれた
- **19:10:26.436**: `[EVENT_SOCKET] Added call_id=in-2025122719102697 to _active_calls`（既存ログ）
- **19:10:29.870**: 最初のRTP音声データが処理された
- **19:10:34.491**: ASR処理が開始された（`on_new_audio`が呼ばれた）
- **19:10:59.392**: 通話終了、`_active_calls`から削除された

#### 既存のログは正常に出力されている
- `[RTP_RAW]`: 正常に出力（Len=172のパケットを確認）
- `[RTP_AUDIO_RMS]`: 正常に出力
- `[ASR_DEBUG]`: 正常に出力
- `[EVENT_SOCKET]`: 正常に出力

---

## 【通話の時系列（詳細）】

### 通話ID: `in-2025122719102697`

| 時刻 | イベント | ログ |
|------|----------|------|
| 19:10:26.436 | 通話開始 | `[EVENT_SOCKET] Added call_id=in-2025122719102697 to _active_calls` |
| 19:10:26.436 | on_call_start呼び出し | `[AICORE] on_call_start() call_id=in-2025122719102697` |
| 19:10:29.870 | 最初のRTP音声処理 | `[RTP_AUDIO_RMS] call_id=in-2025122719102697 stage=ulaw_decode` |
| 19:10:34.491 | ASR処理開始 | `[ASR_DEBUG] Calling on_new_audio with 640 bytes` |
| 19:10:35.254 | 無音検出 | `[SILENCE DETECTED] 5.5s of silence call_id=in-2025122719102697` |
| 19:10:59.392 | 通話終了 | `[EVENT_SOCKET] Removed call_id=in-2025122719102697 from _active_calls` |

### 重要な観察

1. **通話は正常に処理されている**
   - `_active_calls`への追加・削除が正常に行われている
   - ASR処理も正常に動作している
   - RTPパケットの処理も正常

2. **追加したログが全く出力されていない**
   - `[RTP_ENTRY]`: 0件
   - `[CALL_START_TRACE] [LOC_START]`: 0件
   - 既存のログ（`[EVENT_SOCKET] Added call_id=...`）は出力されている

3. **矛盾点**
   - `[EVENT_SOCKET] Added call_id=in-2025122719102697 to _active_calls`は出力されている
   - これは`realtime_gateway.py:4676`行目の既存ログ
   - しかし、その直前に追加した`[CALL_START_TRACE] [LOC_START]`ログ（4674行目）は出力されていない

---

## 【現在のアクティブな通話本数】

### 確認方法
```bash
grep -E "Added.*_active_calls|Removed.*_active_calls" /opt/libertycall/logs/realtime_gateway.log | tail -20
```

### 結果
- **最新の追加**: `in-2025122719102697` (19:10:26.436)
- **最新の削除**: `in-2025122719102697` (19:10:59.392)

### 現在のアクティブな通話本数
- **推定: 0件**
- 理由: 最新の通話は既に終了し、`_active_calls`から削除されている

---

## 【問題の分析】

### 仮説1: サービスが再起動されていない（最も可能性が高い）

**証拠**:
- 追加したログが全く出力されていない（0件）
- 既存のログは正常に出力されている
- コードは修正されているが、実行中のプロセスが古いコードを使用している可能性

**確認方法**:
```bash
ps aux | grep realtime_gateway
# プロセスIDを確認し、そのプロセスが使用しているファイルを確認
ls -l /proc/<PID>/exe
```

### 仮説2: ログが別の場所に出力されている

**可能性**:
- `print()`文は標準出力に出力されるが、ログファイルには記録されない
- `systemd_gateway_stdout.log`に出力されている可能性

**確認結果**:
- 標準出力ログファイルも確認したが、該当ログは見つからなかった

### 仮説3: コードの実行パスが異なる

**可能性**:
- 修正したファイルとは別のファイルが実行されている
- モジュールのインポートパスが異なる

**確認が必要**:
- 実行中のプロセスが使用している実際のファイルパスを確認

---

## 【コードの確認】

### 修正箇所の確認

1. **`realtime_gateway.py:1909`** - `[RTP_ENTRY]`ログ
   ```python
   print(f"[RTP_ENTRY] Time={current_time:.3f} Len={len(data)} Addr={addr}", flush=True)
   ```

2. **`realtime_gateway.py:4674`** - `[CALL_START_TRACE]`ログ（event_socket）
   ```python
   print(f"[CALL_START_TRACE] [LOC_START] Adding {effective_call_id} to _active_calls (event_socket) at {time.time():.3f}", flush=True)
   ```

### 既存のログとの比較

- **既存ログ（4676行目）**: `[EVENT_SOCKET] Added call_id=...` - **出力されている**
- **追加ログ（4674行目）**: `[CALL_START_TRACE] [LOC_START]` - **出力されていない**

**矛盾**: 4674行目のログが出力されないのに、4676行目のログが出力されるのは不可解

---

## 【次のステップ】

### 1. サービス再起動の確認
```bash
sudo systemctl restart libertycall
```

### 2. プロセス確認
```bash
ps aux | grep realtime_gateway
# プロセスIDを確認
ls -l /proc/<PID>/exe
# 実際に実行されているファイルを確認
```

### 3. コードの再確認
- `realtime_gateway.py`の修正箇所が正しく保存されているか確認
- ファイルのタイムスタンプを確認

### 4. 標準出力の直接確認
```bash
# サービスを再起動後、リアルタイムで標準出力を確認
journalctl -u libertycall -f
```

---

## 【結論】

1. **追加したログが依然として全く出力されていない**
   - `[RTP_ENTRY]`: 0件
   - `[CALL_START_TRACE]`: 0件

2. **通話は正常に処理されている**
   - `_active_calls`への追加・削除は正常
   - ASR処理も正常に動作
   - RTPパケットの処理も正常

3. **最も可能性が高い原因**
   - **サービスが再起動されていない**（修正が反映されていない）
   - 実行中のプロセスが古いコードを使用している

4. **推奨アクション**
   - **サービスを再起動**してから再度テスト
   - 再起動後、プロセスが使用しているファイルパスを確認
   - 標準出力を直接確認（`journalctl -u libertycall -f`）

---

## 【補足情報】

### 現在のアクティブな通話本数
- **0件**（最新の通話は既に終了）

### 通話の処理状況
- **正常**: 通話は正常に処理され、ASRも動作している
- **問題**: 追加したログが出力されていない（デバッグ情報が不足）

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 19:11

