# RTP音声データ処理エラーレポート

## テスト実施日時
2025-12-27 18:23-18:24頃（通話ID: `in-2025122718233335`）

## テスト内容
- 実通話を実施
- 「もしもし」を2回発話
- 反応なし

---

## 重大なエラー発見

### エラー内容

**エラーメッセージ:**
```
[ERROR] __main__: AI Error: cannot access local variable 'audioop' where it is not associated with a value
```

**発生頻度:**
- ほぼすべてのRTPパケット受信時に発生
- 18:24:09頃から連続して発生

**エラーログ例:**
```
2025-12-27 18:24:09,524 [INFO] __main__: RTP_RECV: n=1638 time=1766827449.525 from=('61.213.230.82', 13996) size=172
2025-12-27 18:24:09,525 [ERROR] __main__: AI Error: cannot access local variable 'audioop' where it is not associated with a value
2025-12-27 18:24:09,544 [INFO] __main__: RTP_RECV: n=1639 time=1766827449.545 from=('61.213.230.82', 13996) size=172
2025-12-27 18:24:09,545 [ERROR] __main__: AI Error: cannot access local variable 'audioop' where it is not associated with a value
```

---

## 診断ログの出力状況

### 1. RTP_PAYLOAD_DEBUG
- **出力: なし**
- 理由: エラーにより処理が中断されている可能性

### 2. RTP_AUDIO_RMS (stage=ulaw_decode)
- **出力: なし**
- 理由: エラーにより処理が中断されている可能性

### 3. RTP_AUDIO_RMS (stage=16khz_resample)
- **出力: なし**
- 理由: エラーにより処理が中断されている可能性

### 4. STREAMING_FEED
- **出力: なし**
- 理由: エラーにより処理が中断されている可能性

---

## 問題の原因

### 診断ログ追加時の問題

診断ログを追加した際に、`audioop`モジュールのインポートが適切に行われていない可能性があります。

**追加したコード:**
```python
# 【診断用】16kHz変換後、on_new_audio呼び出し直前のRMS値確認
try:
    import audioop  # ← ここでインポート
    rms_16k = audioop.rms(pcm16k_chunk, 2)
    ...
except Exception as e:
    ...
```

**問題点:**
- `audioop`はファイルの先頭で既にインポートされている（`import audioop`）
- しかし、診断ログ追加部分で`import audioop`を再度実行している
- 既存のコードで`audioop`を使用している箇所で、スコープの問題が発生している可能性

**既存のコード:**
```python
# realtime_gateway.py の先頭
import audioop  # ← 既にインポートされている

# handle_rtp_packet内
pcm16_8k = audioop.ulaw2lin(pcm_data, 2)  # ← 既存のコード
rms = audioop.rms(pcm16_8k, 2)  # ← 既存のコード
```

---

## 現在のアクティブな通話本数

**最新の通話:**
- 通話ID: `in-2025122718233335`
- ステータス: **終了済み**（`on_call_end` が呼ばれている）
- 終了時刻: 2025-12-27 18:24:11

**ログ確認結果:**
```
2025-12-27 18:24:11,028 [INFO] [EVENT_SOCKET] Received event: call_end uuid=fb887045-5e8c-4e98-b819-0fab3810422e
2025-12-27 18:24:11,028 [INFO] [AICORE] on_call_end() call_id=in-2025122718233335
2025-12-27 18:24:11,038 [INFO] [EVENT_SOCKET] Removed call_id=in-2025122718233335 from _active_calls
```

**現在のアクティブな通話本数:**
- **0件**（最新の通話は終了済み）

---

## RTPパケット受信状況

**確認結果:**
- RTPパケットは正常に受信されている
- パケットサイズ: 172バイト（RTPヘッダー12バイト + ペイロード160バイト）
- 受信元: `('61.213.230.82', 13996)` と `('160.251.170.253', 7174)`
- 受信頻度: 約20ms間隔（正常）

**ログ例:**
```
2025-12-27 18:24:09,424 [INFO] RTP_RECV: n=1633 time=1766827449.425 from=('61.213.230.82', 13996) size=172
2025-12-27 18:24:09,444 [INFO] [RTP_RECV_RAW] from=('61.213.230.82', 13996), len=172 (pcap)
```

---

## 結論

### 根本原因

**診断ログ追加時に`audioop`モジュールのインポートが問題を引き起こしている**

1. **エラー発生箇所:**
   - `handle_rtp_packet`メソッド内の診断ログ追加部分
   - `audioop`モジュールのスコープ問題

2. **影響:**
   - 音声データ処理が中断されている
   - RMS値の計算が実行されていない
   - ASRへの音声データ送信が失敗している可能性

3. **結果:**
   - 診断ログが一切出力されていない
   - 音声認識が動作していない

---

## 推奨される対処方法

### 1. 診断ログの修正（最優先）

**問題箇所:**
- `/opt/libertycall/gateway/realtime_gateway.py`
- 診断ログ追加部分の`import audioop`を削除
- `audioop`はファイルの先頭で既にインポートされているため、再インポート不要

**修正内容:**
```python
# 【診断用】16kHz変換後、on_new_audio呼び出し直前のRMS値確認
try:
    # import audioop  # ← この行を削除（既にファイル先頭でインポート済み）
    rms_16k = audioop.rms(pcm16k_chunk, 2)
    ...
except Exception as e:
    ...
```

### 2. エラーハンドリングの改善

診断ログ追加部分のエラーハンドリングを改善し、エラーが発生しても処理を継続できるようにする。

---

## 補足情報

- **エラー発生時刻:** 2025-12-27 18:24:09頃から連続
- **エラー発生頻度:** ほぼすべてのRTPパケット受信時
- **影響範囲:** 音声データ処理全体
- **診断ログ:** 一切出力されていない（エラーにより処理が中断）

**修正後、再度テストを実施してください。**

