# ASR動作状況確認レポート

## 調査日時
2025-12-27 18:42頃

## 調査対象通話ID
`in-2025122718411977`

---

## 【手順1: ASRストリーム起動確認】

### 結果
```
ASRストリーム起動: あり（部分的）
起動時刻: 18:41:40,299
enable_asr呼び出し: あり
```

### 詳細
- **enable_asr()呼び出し**: 2025-12-27 18:41:40,299
  - `[FS_RTP_MONITOR] AICore.enable_asr() called successfully for uuid=820d2798-810e-4227-ac4b-21102fb2cb1c call_id=in-2025122718411977 client_id=000`
- **REQUEST_GEN Generator開始**: 2025-12-27 18:41:40,439
  - `[REQUEST_GEN] Generator started for call_id=in-2025122718411977`
- **ASR_STREAM/STREAMING_STARTログ**: 見つからない
  - ASRストリームは部分的に起動しているが、完全には起動していない可能性

---

## 【手順2: 音声データ送信状況確認】

### 結果
```
STREAMING_FEED出力: なし
→ on_new_audioが呼ばれていない可能性
```

### 詳細
- **STREAMING_FEEDログ**: 見つからない
- **RTP_AUDIO_RMSログ**: 見つからない
- **on_new_audio呼び出し**: 見つからない
- **判定**: 音声データがASRに送信されていない

---

## 【手順3: ASR結果確認】

### 結果
```
ASR結果: なし
→ Google ASRが反応していない
```

### 詳細
- **ASR_GOOGLE_RAWログ**: 見つからない
- **ASR_TRANSCRIPTログ**: 見つからない
- **on_transcriptログ**: 見つからない
- **判定**: Google ASRが音声を認識していない

---

## 【手順4: RTPパケットのペイロード分析】

### 結果
```
first_bytes分析:
- 0xFF含有率: 17.0%（高）
- 0x7C-0x7F含有率: 45.0%（非常に高い）
- 判定: 無音/ノイズ（正常なμ-lawデータではない）
```

### 詳細
- **RTP_PAYLOAD_DEBUGパケット数**: 5個
- **first_bytesの内容**:
  ```
  ff7c7dfe7d7efdfefeff
  7cfffffffffeff7c7efe
  7b7cfbfdfffdfdff7eff
  7eff7b7cfefffefffefe
  fffffffcfd7a787efeff
  ```
- **分析結果**:
  - 0xFF含有率: 17.0%（高）
  - 0x7C-0x7F含有率: 45.0%（非常に高い）
  - μ-lawエンコーディングでは、0xFFは無音、0x7C-0x7Fは非常に小さい音声レベルを示す
  - **判定**: 無音またはノイズの可能性が高い

---

## 【問題の分析】

### 1. ASRストリームは部分的に起動
- `enable_asr()`は呼ばれている
- `REQUEST_GEN Generator`は開始されている
- しかし、`STREAMING_FEED`や`on_new_audio`のログが見つからない

### 2. 音声データがASRに送信されていない
- `STREAMING_FEED`ログが見つからない
- `RTP_AUDIO_RMS`ログが見つからない
- `on_new_audio`が呼ばれていない可能性

### 3. RTPパケットの内容が無音/ノイズ
- 0xFF含有率: 17.0%（高）
- 0x7C-0x7F含有率: 45.0%（非常に高い）
- 正常な音声データではない

### 4. 通話終了が早すぎる
- RTP_PAYLOAD_DEBUGが出力された時点（18:41:49）で既に通話が終了している
- 通話開始（18:41:19）から約30秒で終了

---

## 【根本原因の仮説】

### 仮説1: RTPパケットが通話終了後に受信されている
- RTP_PAYLOAD_DEBUGが出力された時点で既に通話が終了している
- 通話終了後のRTPパケットは処理されない（`already ended`）

### 仮説2: 音声データが正しく受信されていない
- RTPパケットの内容が無音/ノイズ
- ユーザーの音声が正しく受信されていない可能性

### 仮説3: ASRストリームが完全に起動していない
- `enable_asr()`は呼ばれているが、`STREAMING_FEED`が出力されていない
- `on_new_audio`が呼ばれていない可能性

---

## 【次のステップ】

1. **通話終了時刻の確認**
   - なぜ通話が18:41:49より前に終了したのか確認
   - `on_call_end`のログを確認

2. **RTPパケット受信タイミングの確認**
   - 通話中にRTPパケットが受信されていたか確認
   - `RTP_RECV`ログを確認

3. **ASRストリーム起動の詳細確認**
   - `on_new_audio`が呼ばれていない原因を特定
   - `STREAMING_FEED`が出力されない原因を特定

---

報告完了

