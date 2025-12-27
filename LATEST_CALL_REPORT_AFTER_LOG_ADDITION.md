# 最新通話ログ調査報告書（ログ追加後）

**調査日時**: 2025-12-27 19:10頃  
**対象通話ID**: `in-2025122719082162`  
**調査目的**: 追加した`[RTP_ENTRY]`と`[CALL_START_TRACE]`ログの確認

---

## 【重要な発見】

### 1. 追加したログが全く出力されていない

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

### 2. 既存のログは正常に出力されている

#### `[RTP_RAW]`ログ
- **出力状況**: 正常に出力されている
- **例**: 
  ```
  2025-12-27 19:08:49,875 [INFO] [RTP_RAW] Time=1766830129.875 Len=172 PT=0 SSRC=2f590201 Seq=19859 Mark=0 Addr=('61.213.230.90', 19194)
  ```
- **観察**: すべて`Len=172`（12バイト以上）で、正常なRTPパケット

#### `[RTP_SKIP] [LOC_01]`ログ
- **出力状況**: 大量に出力されている
- **例**:
  ```
  2025-12-27 19:08:49,875 [INFO] [RTP_SKIP] [LOC_01] Time=1766830129.875 call_id=in-2025122719082162 already ended (Active=False). Skipping handle_rtp_packet
  ```
- **観察**: 通話ID `in-2025122719082162` は既に終了している状態でRTPパケットが来ている

---

## 【通話の時系列】

### 通話ID: `in-2025122719082162`

| 時刻 | イベント | ログ |
|------|----------|------|
| 19:08:21.577 | 最初のRTP_SKIP | `[RTP_SKIP] [LOC_01] Time=1766830101.578 call_id=in-2025122719082162 already ended` |
| 19:08:21〜19:08:50 | RTP_SKIP連続出力 | 約1000件以上 |
| 19:08:49.875 | RTP_RAW出力 | `[RTP_RAW] Time=1766830129.875 Len=172 PT=0 SSRC=2f590201` |

### 重要な観察

1. **最初のRTPパケット受信時点で既に通話が終了している**
   - `[RTP_SKIP] [LOC_01]`が最初から出力されている
   - `_active_calls`に通話IDが登録されていない状態

2. **RTP_RAWログは出力されているが、RTP_ENTRYログは出力されていない**
   - `[RTP_RAW]`は`if len(data) >= 12:`の条件内で出力（1922-1923行目）
   - `[RTP_ENTRY]`は条件分岐の前で出力（1909行目）
   - **矛盾**: `[RTP_ENTRY]`が出力されないのに`[RTP_RAW]`が出力されるのは不可解

3. **`handle_rtp_packet`は実行されている**
   - `[RTP_SKIP] [LOC_01]`は`handle_rtp_packet`内の2022行目で出力
   - つまり、`handle_rtp_packet`は呼ばれているが、先頭の`[RTP_ENTRY]`ログが出力されていない

---

## 【現在のアクティブな通話本数】

### 確認方法
```bash
grep -E "Added.*_active_calls|Removed.*_active_calls" /opt/libertycall/logs/realtime_gateway.log | tail -20
```

### 結果
- **該当ログが見つからない**（最新のログファイルに存在しない）

### 推定
- **0件**（通話ID `in-2025122719082162` は`_active_calls`に追加されていない）

---

## 【問題の分析】

### 仮説1: サービスが再起動されていない

**証拠**:
- サービス起動時刻: `2025-12-27 18:05:28`
- 修正実施時刻: おそらく18:05以降
- 追加したログが全く出力されていない

**確認方法**:
```bash
systemctl status libertycall
ps aux | grep realtime_gateway
```

**結果**:
- サービスは18:05:28に起動
- プロセスID: 2174131（19:00に起動）
- **realtime_gateway.pyは別プロセスで実行されている可能性**

### 仮説2: ログが別の場所に出力されている

**可能性**:
- `print()`文は標準出力に出力されるが、ログファイルには記録されない
- `systemd_gateway_stdout.log`に出力されている可能性

**確認が必要**:
```bash
tail -1000 /opt/libertycall/logs/systemd_gateway_stdout.log | grep -E "\[RTP_ENTRY\]|\[CALL_START_TRACE\]"
```

### 仮説3: コードが実際に実行されていない

**可能性**:
- 別の`handle_rtp_packet`メソッドが呼ばれている
- キャッシュされた古いコードが実行されている

---

## 【次のステップ】

### 1. サービス再起動の確認
```bash
sudo systemctl restart libertycall
```

### 2. 標準出力ログの確認
```bash
tail -1000 /opt/libertycall/logs/systemd_gateway_stdout.log | grep -E "\[RTP_ENTRY\]|\[CALL_START_TRACE\]"
```

### 3. プロセス確認
```bash
ps aux | grep realtime_gateway
# プロセスIDを確認し、そのプロセスが使用しているファイルを確認
ls -l /proc/2174131/exe
```

### 4. コードの再確認
- `realtime_gateway.py`の1909行目に`[RTP_ENTRY]`ログが正しく追加されているか確認
- 2114, 2140, 3771, 4674行目に`[CALL_START_TRACE]`ログが正しく追加されているか確認

---

## 【結論】

1. **追加したログが全く出力されていない**
   - `[RTP_ENTRY]`: 0件
   - `[CALL_START_TRACE]`: 0件

2. **既存のログは正常に出力されている**
   - `[RTP_RAW]`: 正常出力
   - `[RTP_SKIP] [LOC_01]`: 正常出力

3. **最も可能性が高い原因**
   - **サービスが再起動されていない**（修正が反映されていない）
   - または、**ログが別の場所に出力されている**（標準出力ログファイル）

4. **推奨アクション**
   - サービスを再起動してから再度テスト
   - 標準出力ログファイルも確認

---

**報告者**: AI Assistant  
**報告日時**: 2025-12-27 19:10

