# 最新通話ログ分析レポート（識別子付きログ版）

## 通話情報

- **通話ID**: `in-2025122719005836`
- **FreeSWITCH UUID**: `8d9bf71a-6ad2-4149-87d9-ad74e07d0947`
- **通話開始時刻**: 2025-12-27 19:00:58
- **通話終了時刻**: 2025-12-27 19:02:00
- **通話継続時間**: 約1分22秒

---

## 【重大発見1】RTP_RAWログが全く出力されていない

### 発見内容

- **RTP_RAWログ件数**: **0件**
- **RTP_PAYLOAD_DEBUGログ件数**: **5件**

### 意味

1. `handle_rtp_packet`メソッドの**冒頭（1921行目）のRTP_RAWログが実行されていない**
2. しかし、`handle_rtp_packet`メソッドの**後半（2012行目）のRTP_PAYLOAD_DEBUGは実行されている**

### コード上の矛盾

```1906:1924:/opt/libertycall/gateway/realtime_gateway.py
async def handle_rtp_packet(self, data: bytes, addr: Tuple[str, int]):
    # 【追加】受信直後の生ログ（デバッグ用）
    current_time = time.time()
    
    # 先頭12バイト(RTPヘッダ)を解析
    try:
        if len(data) >= 12:
            # ... RTPヘッダ解析 ...
            print(f"[RTP_RAW] Time={current_time:.3f} ...", flush=True)
            self.logger.info(f"[RTP_RAW] Time={current_time:.3f} ...")
    except Exception as e:
        self.logger.warning(f"[RTP_RAW_ERR] Failed to parse header: {e}")
```

- RTP_RAWログは**1912行目の`if len(data) >= 12:`条件内**にある
- RTP_PAYLOAD_DEBUGは**2012行目**で出力されている
- **RTP_PAYLOAD_DEBUGが出力されている = handle_rtp_packetは実行されている**
- **しかし、RTP_RAWログが出力されていない = 1912行目の条件が満たされていない可能性**

### 仮説

1. **`len(data) < 12`のパケットが来ている**（RTPヘッダが不完全）
2. **例外が発生してRTP_RAW_ERRも出力されていない**（例外処理が機能していない）
3. **コードが実際に実行されていない**（別のhandle_rtp_packetが実行されている）

---

## 【重大発見2】通話終了処理（LOC_02〜04）が全く実行されていない

### 発見内容

- **LOC_02ログ**: **0件**（3573行目: 通話終了時のクリーンアップ1）
- **LOC_03ログ**: **0件**（3712行目: 通話終了時のクリーンアップ2）
- **LOC_04ログ**: **0件**（4723行目: EVENT_SOCKET経由の通話終了）
- **CALL_STATEログ**: **0件**

### 意味

1. **通話終了処理が実行されていない**
2. **しかし、通話は既に終了している**（RTP_SKIP [LOC_01]が大量に出力されている）

### 矛盾点

- **RTP_SKIP [LOC_01]**: 大量に出力されている（通話終了後にパケットが届いている）
- **LOC_02〜04**: 全く出力されていない（通話終了処理が実行されていない）

### 仮説

1. **通話IDが`_active_calls`に追加されていない**
2. **通話終了処理が別の経路で実行されている**（LOC_02〜04以外）
3. **通話終了処理が実行されずに、`_active_calls`から削除されている**

---

## 【重大発見3】通話IDが_active_callsに追加されていない可能性

### 発見内容

- **"Added call_id=in-2025122719005836 to _active_calls"ログ**: **見つからない**

### 意味

1. **通話開始時に`_active_calls`に追加されていない**
2. **そのため、最初から`effective_call_id not in self._active_calls`がTrue**
3. **そのため、RTP_SKIP [LOC_01]が最初から出力されている**

### 確認が必要なログ

```bash
grep "in-2025122719005836" /opt/libertycall/logs/realtime_gateway.log | grep -E "Added.*_active_calls|EVENT_SOCKET.*Added"
```

**結果**: **見つからない**

---

## 【時系列分析】

### 通話開始から終了まで

| 時刻 | イベント | ログ |
|------|----------|------|
| 19:00:58.771 | 通話開始 | `[FS_RTP_MONITOR] Mapped call_id=in-2025122719005836` |
| 19:01:19.792 | ASR有効化 | `[FS_RTP_MONITOR] AICore.enable_asr() called successfully` |
| 19:01:19.884 | ASRストリーム開始 | `[REQUEST_GEN] Generator started` |
| 19:01:36.868 | **最初のRTPパケット受信** | `[RTP_PAYLOAD_DEBUG]` + `[RTP_SKIP] [LOC_01]` |
| 19:01:36.887〜 | **RTP_SKIP [LOC_01]が連続出力** | 約50件以上 |
| 19:02:00.327 | 通話終了 | 最後のRTP_SKIPログ |

### 重要な観察

1. **19:01:36.868**: 最初のRTPパケットが届いた時点で、既に`_active_calls`に存在しない
2. **RTP_RAWログが全く出力されていない**: handle_rtp_packetの冒頭が実行されていない
3. **RTP_PAYLOAD_DEBUGは出力されている**: handle_rtp_packetの後半は実行されている

---

## 【現在のアクティブな通話本数】

### 確認方法

```bash
grep -E "Added.*_active_calls|Removed.*_active_calls" /opt/libertycall/logs/realtime_gateway.log | tail -10
```

### 最新の状態

- **最新の追加**: `in-2025122718375146` (18:37:51)
- **最新の削除**: `in-2025122718275960` (18:38:23)

### 現在のアクティブな通話本数

**推定: 0件**（最新の通話`in-2025122719005836`は`_active_calls`に追加されていないため）

---

## 【問題の根本原因（仮説）】

### 仮説1: 通話IDが_active_callsに追加されていない

**証拠**:
- "Added call_id=in-2025122719005836 to _active_calls"ログが見つからない
- 最初のRTPパケット受信時点で既に`_active_calls`に存在しない

**影響**:
- 最初から`effective_call_id not in self._active_calls`がTrue
- そのため、RTP_SKIP [LOC_01]が最初から出力されている
- 音声処理が一切実行されない

### 仮説2: RTP_RAWログが出力されない理由

**証拠**:
- RTP_RAWログが0件
- RTP_PAYLOAD_DEBUGは5件（handle_rtp_packetは実行されている）

**可能性**:
1. `len(data) < 12`のパケットが来ている
2. 例外が発生しているが、RTP_RAW_ERRも出力されていない
3. コードが実際に実行されていない（別のhandle_rtp_packetが実行されている）

### 仮説3: 通話終了処理が実行されていない

**証拠**:
- LOC_02〜04のログが全く出力されていない
- しかし、通話は既に終了している

**可能性**:
1. 通話終了処理が別の経路で実行されている
2. 通話終了処理が実行されずに、`_active_calls`から削除されている
3. `_active_calls`に追加されていないため、削除処理も実行されていない

---

## 【次の調査ステップ】

### 1. 通話開始時のイベント確認

```bash
grep "in-2025122719005836" /opt/libertycall/logs/realtime_gateway.log | grep -E "CHANNEL_CREATE|CHANNEL_ANSWER|EVENT_SOCKET"
```

### 2. _active_callsへの追加処理の確認

```bash
grep -n "Added.*_active_calls\|_active_calls.add" /opt/libertycall/gateway/realtime_gateway.py
```

### 3. RTP_RAWログが出力されない理由の確認

```bash
# パケットサイズの確認
grep "in-2025122719005836" /opt/libertycall/logs/realtime_gateway.log | grep "RTP_PAYLOAD_DEBUG" | head -1
```

### 4. 例外処理の確認

```bash
grep "in-2025122719005836" /opt/libertycall/logs/realtime_gateway.log | grep -E "RTP_RAW_ERR|Exception|Error"
```

---

## 【結論】

1. **RTP_RAWログが全く出力されていない**: handle_rtp_packetの冒頭が実行されていない、または条件が満たされていない
2. **通話終了処理（LOC_02〜04）が全く実行されていない**: 通話終了処理が別の経路で実行されている、または実行されていない
3. **通話IDが_active_callsに追加されていない可能性**: 通話開始時に`_active_calls`に追加されていないため、最初からRTP_SKIPが出力されている

**最も可能性が高い根本原因**: **通話IDが`_active_calls`に追加されていない**

これにより、最初から`effective_call_id not in self._active_calls`がTrueとなり、RTPパケットが全てスキップされている可能性が高い。

