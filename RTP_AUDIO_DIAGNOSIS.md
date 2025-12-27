# RTP音声データ抽出処理の診断レポート

## 診断実施日時
2025-12-27 18:30頃

## 診断内容

### ステップ1: handle_rtp_packetの音声抽出部分の確認

**確認結果:**

1. **RTPペイロード抽出（1982行目）**
   ```python
   pcm_data = data[12:]  # RTPヘッダー12バイトをスキップ
   ```
   - ✅ **正しい**: RTPヘッダーは12バイトなので、`data[12:]`でペイロードを抽出している

2. **μ-lawデコード（2204行目）**
   ```python
   pcm16_8k = audioop.ulaw2lin(pcm_data, 2)  # μ-law → PCM16 (8kHz)
   rms = audioop.rms(pcm16_8k, 2)
   ```
   - ✅ **正しい**: `audioop.ulaw2lin`を使用してμ-lawをPCM16に変換している
   - サンプルレート: 8kHz

3. **8kHz → 16kHz変換（2269行目）**
   ```python
   pcm16_array = np.frombuffer(pcm16_8k_ns, dtype=np.int16)
   pcm16k_array = resample_poly(pcm16_array, 2, 1)  # 8kHz → 16kHz
   pcm16k_chunk = pcm16k_array.astype(np.int16).tobytes()
   ```
   - ✅ **正しい**: `scipy.signal.resample_poly`を使用して8kHz → 16kHzに変換している

4. **on_new_audio呼び出し（2359行目）**
   ```python
   self.ai_core.on_new_audio(effective_call_id, pcm16k_chunk)
   ```
   - ✅ **正しい**: 16kHz PCM16データを`on_new_audio`に送信している

**結論:**
- コード上は正しく実装されている
- 各段階での変換処理は適切

---

### ステップ2: 診断ログの追加

**追加した診断ログ:**

1. **RTPペイロード抽出直後（1984-1991行目）**
   - ログタグ: `[RTP_PAYLOAD_DEBUG]`
   - 内容: ペイロード長、最初の10バイトの16進数表示
   - 出力頻度: 最初の5回のみ

2. **μ-lawデコード後（2204行目以降）**
   - ログタグ: `[RTP_AUDIO_RMS]` (stage=ulaw_decode)
   - 内容: RMS値、最大振幅、サンプル値
   - 出力頻度: 最初の50回は詳細、その後は10回に1回

3. **16kHz変換後、on_new_audio呼び出し直前（2359行目前）**
   - ログタグ: `[RTP_AUDIO_RMS]` (stage=16khz_resample)
   - 内容: RMS値、最大振幅、サンプル値
   - 出力頻度: 最初の50回は詳細、その後は10回に1回

**診断ログの出力形式:**
```
[RTP_PAYLOAD_DEBUG] call_id=... payload_len=... first_bytes=...
[RTP_AUDIO_RMS] call_id=... stage=ulaw_decode len=... rms=... max_amplitude=...
[RTP_AUDIO_SAMPLES] call_id=... first_5_samples=(...)
[RTP_AUDIO_RMS] call_id=... stage=16khz_resample len=... rms=... max_amplitude=...
[RTP_AUDIO_SAMPLES] call_id=... stage=16khz first_5_samples=(...)
```

---

### ステップ3: RTPパケットのペイロード抽出の確認

**確認結果:**

1. **RTPヘッダーのスキップ**
   - コード: `pcm_data = data[12:]`
   - ✅ **正しい**: RTPヘッダーは12バイトなので、`data[12:]`でペイロードを抽出している

2. **ペイロードの形式**
   - 形式: μ-law（8kHz）
   - ✅ **正しい**: FreeSWITCHから送信される音声データはμ-law形式

3. **ペイロードサイズ**
   - 通常: 160バイト（20ms分の音声データ、8kHz × 0.02秒 = 160サンプル）
   - ✅ **想定通り**: 20msフレームごとにRTPパケットが送信される

**結論:**
- RTPペイロード抽出は正しく実装されている
- ヘッダースキップも正しい

---

## 診断ログの確認方法

### サービス再起動後、実際の通話で以下を確認:

```bash
# 診断ログを確認
tail -f /opt/libertycall/logs/realtime_gateway.log | grep -E "RTP_PAYLOAD_DEBUG|RTP_AUDIO_RMS|RTP_AUDIO_SAMPLES"
```

### 確認ポイント:

1. **RTPペイロード抽出直後**
   - `first_bytes`が0以外の値か（すべて0なら無音データ）
   - `payload_len`が160バイト程度か

2. **μ-lawデコード後（stage=ulaw_decode）**
   - `rms`値が100以上か（正常な音声の場合）
   - `max_amplitude`が1000以上か（正常な音声の場合）
   - `first_5_samples`が0以外の値か

3. **16kHz変換後（stage=16khz_resample）**
   - `rms`値がμ-lawデコード後と同程度か（変換で失われていないか）
   - `max_amplitude`がμ-lawデコード後と同程度か
   - `first_5_samples`が0以外の値か

4. **ai_core.on_new_audio受信時（既存のログ）**
   - `[STREAMING_FEED]`の`rms`値が1-9しかない場合、16kHz変換後に問題がある可能性

---

## 予想される問題と対処方法

### 可能性1: RTPペイロードが無音データ

**症状:**
- `[RTP_PAYLOAD_DEBUG]`の`first_bytes`がすべて0または0xff
- `[RTP_AUDIO_RMS] stage=ulaw_decode`の`rms`値が1-9

**原因:**
- FreeSWITCHが無音データを送信している
- RTPルーティングの問題

**対処方法:**
- FreeSWITCHの音声ルーティング設定を確認
- RTPポートの設定を確認

### 可能性2: μ-lawデコードが失敗している

**症状:**
- `[RTP_PAYLOAD_DEBUG]`の`first_bytes`は正常
- `[RTP_AUDIO_RMS] stage=ulaw_decode`の`rms`値が1-9

**原因:**
- `audioop.ulaw2lin`の変換に問題がある
- データ形式がμ-lawではない

**対処方法:**
- データ形式を確認（PCM、A-lawなど）
- デコード処理を確認

### 可能性3: 16kHz変換でデータが失われている

**症状:**
- `[RTP_AUDIO_RMS] stage=ulaw_decode`の`rms`値は正常（100以上）
- `[RTP_AUDIO_RMS] stage=16khz_resample`の`rms`値が1-9

**原因:**
- `resample_poly`の変換に問題がある
- 変換処理でデータが失われている

**対処方法:**
- `resample_poly`のパラメータを確認
- 変換処理を確認

---

## 次のステップ

1. **サービスを再起動**
   ```bash
   sudo systemctl restart liberty_gateway.service
   ```

2. **実際の通話を行い、診断ログを確認**
   ```bash
   tail -f /opt/libertycall/logs/realtime_gateway.log | grep -E "RTP_PAYLOAD_DEBUG|RTP_AUDIO_RMS|RTP_AUDIO_SAMPLES"
   ```

3. **各段階のRMS値を比較**
   - RTPペイロード抽出直後
   - μ-lawデコード後
   - 16kHz変換後
   - `on_new_audio`受信時

4. **問題の箇所を特定**
   - どの段階でRMS値が低下しているか確認
   - 該当箇所のコードを修正

---

## 補足情報

- **診断ログの追加場所:**
  - `/opt/libertycall/gateway/realtime_gateway.py`
  - 1984-1991行目: RTPペイロード抽出直後
  - 2204行目以降: μ-lawデコード後
  - 2359行目前: 16kHz変換後、`on_new_audio`呼び出し直前

- **既存のログ:**
  - `[STREAMING_FEED]`: `ai_core.on_new_audio`受信時のRMS値（既存）
  - `[RTP_DEBUG]`: 8kHz PCM16のデバッグ情報（既存、最初の5回のみ）

- **新規追加のログ:**
  - `[RTP_PAYLOAD_DEBUG]`: RTPペイロード抽出直後
  - `[RTP_AUDIO_RMS]`: 各段階のRMS値
  - `[RTP_AUDIO_SAMPLES]`: 各段階のサンプル値

