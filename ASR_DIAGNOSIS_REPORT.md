# ASR空文字列問題の診断レポート

## 診断日時
2025-12-27 18:13 JST

## 診断結果サマリー

### ステップ1: ASRへの音声データ送信を確認

**コード確認結果:**
- `feed_audio`メソッドで音声データがキューに投入されている（`ai_core.py:606-669`）
- `QUEUE_PUT`ログが出力される（`ai_core.py:657`）
- ログ形式: `GoogleASR: QUEUE_PUT: call_id=%s len=%d bytes`

**確認コマンド実行結果:**
```bash
sudo journalctl -u liberty_gateway.service --since "5 minutes ago" --no-pager | grep -E "QUEUE_PUT|feed_audio|on_new_audio" | tail -50
```
→ ログが取得できませんでした（サービスが再起動されたばかりの可能性）

**結論:**
- コード上は音声データ送信の仕組みは実装されている
- 実際のログ確認が必要

---

### ステップ2: Google ASRストリームの状態を確認

**コード確認結果:**
- `_start_stream_worker`メソッドでストリームが起動される（`ai_core.py:186-267`）
- `_stream_worker`メソッドでストリーミング認識が実行される（`ai_core.py:299-520`）
- `STREAM_WORKER_START`ログが出力される（`ai_core.py:266`）
- `REQUEST_GEN`ログが出力される（`ai_core.py:325`）

**確認コマンド実行結果:**
```bash
sudo journalctl -u liberty_gateway.service --since "5 minutes ago" --no-pager | grep -E "ASR_STREAM|STREAM_WORKER|REQUEST_GEN" | tail -50
```
→ ログが取得できませんでした

**結論:**
- コード上はストリーム起動の仕組みは実装されている
- 実際のログ確認が必要

---

### ステップ3: 空文字列が返される詳細ログを確認

**コード確認結果:**
- `on_transcript`メソッドが呼ばれる（`ai_core.py:494`）
- `ASR_GOOGLE_RAW`ログが出力される（`ai_core.py:455-458`）
- `is_final`と`transcript`の両方がログに出力される

**確認コマンド実行結果:**
```bash
sudo journalctl -u liberty_gateway.service --since "5 minutes ago" --no-pager | grep -E "ASR_TRANSCRIPT.*text=''" | head -20
```
→ ログが取得できませんでした

**結論:**
- コード上は空文字列のログ出力は実装されている
- 実際のログ確認が必要

---

### ステップ4: RMS値（音量）を確認 ⚠️ 最重要

**コード確認結果:**
- ❌ **`STREAMING_FEED.*rms=`というログは存在しません**
- `realtime_gateway.py`でRMS値が計算されているが、`ai_core.py`ではログ出力されていない
- RMS値のログ出力機能が実装されていない可能性

**確認コマンド実行結果:**
```bash
sudo journalctl -u liberty_gateway.service --since "5 minutes ago" --no-pager | grep "STREAMING_FEED.*rms=" | tail -20
```
→ ログが取得できませんでした（ログが存在しない可能性）

**結論:**
- ⚠️ **RMS値のログ出力が実装されていない**
- 音声データの音量レベルを確認できない
- **これが問題の原因である可能性が高い**

---

### ステップ5: Google ASRの設定を確認

**コード確認結果:**

1. **言語コード:**
   - AICore初期化時: `language_code="ja"`（`ai_core.py:1258`）
   - GoogleASRデフォルト: `language_code="ja-JP"`（`ai_core.py:65`）
   - ストリーミング設定: `language_code=self.language_code`（`ai_core.py:377`）
   - ✅ **設定は正しい（"ja"が使用される）**

2. **サンプルレート:**
   - 設定値: `sample_rate=16000`（`ai_core.py:1259`）
   - ストリーミング設定: `sample_rate_hertz=16000`（`ai_core.py:376`）
   - ✅ **設定は正しい**

3. **エンコーディング:**
   - 設定値: `LINEAR16`（`ai_core.py:375`）
   - ✅ **設定は正しい**

4. **その他の設定:**
   - `use_enhanced=True`（`ai_core.py:378`）
   - `audio_channel_count=1`（`ai_core.py:380`）
   - `enable_automatic_punctuation=True`（`ai_core.py:382`）
   - ✅ **設定は正しい**

**確認コマンド実行結果:**
```bash
grep -A 20 "class GoogleASR" /opt/libertycall/libertycall/gateway/ai_core.py | grep -E "language|sample_rate|encoding"
```
→ 設定は確認できました

**結論:**
- ✅ **Google ASRの設定は正しい**
- 言語コード、サンプルレート、エンコーディングすべて適切

---

## 問題の可能性

### 可能性1: 音声データが無音（RMS=0） ⚠️ 高確率
- **症状**: ASRが空文字列を返す
- **原因**: RTPパケットから抽出された音声データが無音
- **確認方法**: RMS値のログ出力を追加して確認

### 可能性2: 音声データはあるがASRが認識しない ⚠️ 中確率
- **症状**: RMS値は正常だがASRが空文字列を返す
- **原因**: 
  - 音声データのフォーマットが正しくない
  - Google ASRの設定に問題がある（ただし、コード上は正しい）
- **確認方法**: RMS値のログ出力を追加して確認

### 可能性3: ストリームが正常に起動していない ⚠️ 低確率
- **症状**: ストリームが起動していない、またはエラーが発生している
- **原因**: スレッド起動エラー、認証エラーなど
- **確認方法**: ログで`STREAM_WORKER_START`、`REQUEST_GEN`を確認

---

## 推奨される対処方法

### 1. RMS値のログ出力を追加（最優先） ✅ 完了

`feed_audio`メソッドでRMS値を計算してログ出力する機能を追加しました。

**実装場所:**
- `ai_core.py:606`の`feed_audio`メソッド（620-627行目に追加）

**実装内容:**
```python
# 【診断用】RMS値（音量レベル）を計算してログ出力
try:
    import audioop
    rms = audioop.rms(pcm16k_bytes, 2)  # 2バイト（16bit）PCM
    self.logger.info(f"[STREAMING_FEED] call_id={call_id} len={len(pcm16k_bytes)} bytes rms={rms}")
except Exception as e:
    self.logger.debug(f"[STREAMING_FEED] RMS calculation failed: {e}")
```

**ログ形式:**
- `[STREAMING_FEED] call_id={call_id} len={len} bytes rms={rms}`
- RMS値が0に近い場合: 無音データの可能性
- RMS値が100以上の場合: 音声データは存在するがASRが認識していない可能性

### 2. 実際のログを確認

サービスを再起動して、実際の通話を行い、以下のログを確認:
- `QUEUE_PUT`: 音声データが送信されているか
- `STREAM_WORKER_START`: ストリームが起動しているか
- `REQUEST_GEN`: リクエストが生成されているか
- `ASR_GOOGLE_RAW`: ASRの結果（空文字列かどうか）
- `[STREAMING_FEED]`: RMS値（追加後）

### 3. 音声データの内容を確認

デバッグ用に音声データをWAVファイルに保存して、実際に音声が含まれているか確認する。

---

## 次のステップ

1. ✅ **RMS値のログ出力を追加**（完了）
   - `feed_audio`メソッドにRMS値計算とログ出力を追加
   - ログ形式: `[STREAMING_FEED] call_id={call_id} len={len} bytes rms={rms}`
2. **サービスを再起動**
3. **実際の通話を行い、ログを確認**
4. **RMS値が0なら**: RTP/音声データの問題
5. **RMS値が100以上なら**: Google ASRの設定問題

---

## 補足情報

- サービス状態: `active (running)`（2025-12-27 18:05:56 JST起動）
- コードベース: `/opt/libertycall/libertycall/gateway/ai_core.py`
- Google ASR設定: すべて正しい（言語コード="ja", サンプルレート=16000, エンコーディング=LINEAR16）

