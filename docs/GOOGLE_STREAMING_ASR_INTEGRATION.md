# Google Streaming ASR統合ドキュメント

## 概要

既存のFreeSWITCH + LibertyCall構成に、Google Speech-to-Text Streaming APIを統合し、
着信から案内・ASRリアルタイム解析・無反応催促3回・自動切断までを制御する構成を実装しました。

## 動作フロー

```
着信
  ↓
FreeSWITCH: 000_8k.wav 再生
  ↓
FreeSWITCH: 001_8k.wav 再生
  ↓
FreeSWITCH: 002_8k.wav 再生
  ↓
Google Streaming ASR開始（realtime_gateway.pyから音声ストリームを受信）
  ↓
10秒無反応 → 催促1（000-004_8k.wav）
  ↓
さらに10秒無反応 → 催促2（000-005_8k.wav）
  ↓
さらに10秒無反応 → 催促3（000-006_8k.wav）
  ↓
さらに10秒発話なし → 切断
  ↓
発話あり → ASR認識 → テキスト復唱 → 切断
```

## ファイル構成

```
/opt/libertycall/
├── google_stream_asr.py          # Google Streaming ASRラッパー
├── asr_handler.py                  # 着信制御とASR統合
├── gateway/
│   └── realtime_gateway.py         # RTP入力処理（ASR接続追加済み）
├── gateway_event_listener.py      # FreeSWITCHイベント監視（ASRハンドラー起動追加済み）
└── clients/000/audio/
    ├── 000_8k.wav                  # 初回アナウンス1
    ├── 001_8k.wav                  # 初回アナウンス2
    ├── 002_8k.wav                  # 初回アナウンス3
    ├── 000-004_8k.wav              # 催促1
    ├── 000-005_8k.wav              # 催促2
    └── 000-006_8k.wav              # 催促3
```

## 主要コンポーネント

### 1. google_stream_asr.py

Google Speech-to-Text Streaming APIのラッパークラス。

**主な機能:**
- 音声ストリームのリアルタイム認識
- 認識結果の取得
- ストリーミング制御（開始・停止）

**使用方法:**
```python
from google_stream_asr import GoogleStreamingASR

asr = GoogleStreamingASR(language_code="ja-JP", sample_rate=16000)
asr.start_stream()

# 音声データを追加
asr.add_audio(pcm16k_chunk)

# 認識結果を確認
if asr.has_input():
    text = asr.get_text()
    print(f"認識結果: {text}")
```

### 2. asr_handler.py

着信制御とASR統合を行うハンドラー。

**主な機能:**
- 着信時のASR開始
- 無反応監視（10秒ごとに催促）
- 発話検出時の処理（復唱・切断）
- FreeSWITCH ESLコマンド実行

**使用方法:**
```python
from asr_handler import get_or_create_handler, remove_handler

# 着信時
handler = get_or_create_handler(call_id)
handler.on_incoming_call()

# 音声データを送信
handler.on_audio_chunk(pcm16k_chunk)

# 通話終了時
remove_handler(call_id)
```

### 3. realtime_gateway.py（修正箇所）

RTPパケット受信時に、Google Streaming ASRへ音声データを送信する処理を追加。

**修正内容:**
- `handle_rtp_packet()`内で`pcm16k_chunk`生成後、ASRハンドラーへ送信
- ASRハンドラーの初期化と管理

### 4. gateway_event_listener.py（修正箇所）

FreeSWITCHイベント監視時に、ASRハンドラーを起動する処理を追加。

**修正内容:**
- `CHANNEL_ANSWER`イベントでASRハンドラーを起動
- `CHANNEL_HANGUP`イベントでASRハンドラーを停止

## 設定

### Google Cloud認証

環境変数`GOOGLE_APPLICATION_CREDENTIALS`を設定してください。

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json"
```

または、`systemd`サービスの場合は`Environment`ディレクティブで設定：

```ini
Environment="GOOGLE_APPLICATION_CREDENTIALS=/opt/libertycall/key/google_tts.json"
```

### 音声ファイルの配置

以下の音声ファイルを`/opt/libertycall/clients/000/audio/`に配置してください：

- `000_8k.wav` - 初回アナウンス1
- `001_8k.wav` - 初回アナウンス2
- `002_8k.wav` - 初回アナウンス3
- `000-004_8k.wav` - 催促1
- `000-005_8k.wav` - 催促2
- `000-006_8k.wav` - 催促3

## 動作確認

### 1. ログ確認

```bash
# ASRハンドラーのログ確認
tail -f /tmp/gateway_*.log | grep -E "ASRHandler|GoogleStreamingASR"

# realtime_gatewayのログ確認
tail -f /tmp/gateway_*.log | grep -E "STREAMING_FEED|ASR"
```

### 2. 通話テスト

1. FreeSWITCHに着信
2. 000〜002の再生を確認
3. ASR開始をログで確認
4. 無反応時の催促を確認
5. 発話時の認識結果を確認

## トラブルシューティング

### ASRが起動しない

- `gateway_event_listener.py`が起動しているか確認
- `CHANNEL_ANSWER`イベントが受信されているか確認
- ESL接続が正常か確認

### 音声が認識されない

- `realtime_gateway.py`で`pcm16k_chunk`が生成されているか確認
- `asr_handler.on_audio_chunk()`が呼び出されているか確認
- Google Cloud認証情報が正しいか確認

### 催促が再生されない

- 音声ファイルが存在するか確認
- ESL接続が正常か確認
- `_monitor_silence()`スレッドが動作しているか確認

## 注意事項

1. **音声ファイルの再生タイミング**
   - 000〜002の再生はFreeSWITCHのdialplanで実行される
   - ASRハンドラーは再生完了を待ってから監視を開始（約10秒後）

2. **ストリーミングモード**
   - Google Streaming ASRはストリーミングモードで動作
   - 音声データはリアルタイムで送信される

3. **ESL接続**
   - ASRハンドラーは独立したESL接続を使用
   - 接続エラー時は自動リカバリを試みる

4. **スレッド管理**
   - 無反応監視は別スレッドで実行
   - 通話終了時に適切にクリーンアップされる

## 関連ファイル

- `google_stream_asr.py` - Google Streaming ASRラッパー
- `asr_handler.py` - 着信制御とASR統合
- `gateway/realtime_gateway.py` - RTP入力処理
- `gateway_event_listener.py` - FreeSWITCHイベント監視
- `freeswitch/dialplan/default.xml` - 音声ファイル再生設定

