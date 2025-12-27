# ASR問題の調査レポート

**調査日時**: 2025-12-27 22:27  
**通話ID**: `in-2025122722230530`

---

## 【ステップ1】ASR有効化

### 実行結果

```bash
$ ls -la /tmp/asr_enable_*.flag
ls: cannot access '/tmp/asr_enable_*.flag': No such file or directory
```

**結果**: ASR有効化フラグファイルは存在しない

```bash
$ echo "LC_ASR_STREAMING_ENABLED=$LC_ASR_STREAMING_ENABLED"
LC_ASR_STREAMING_ENABLED=1
```

**結果**: 環境変数は有効（`1`）

```bash
$ ls -la /opt/libertycall/config/google-credentials.json
-rw------- 1 root root 2348 Dec 26 15:21 /opt/libertycall/config/google-credentials.json

$ echo "GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
GOOGLE_APPLICATION_CREDENTIALS=
```

**結果**: 
- 認証ファイルは存在 ✅
- 環境変数は未設定 ❌

---

## 【ステップ2】ASRストリーミング

### ログ

```
2025-12-27 22:24:20,473 [INFO] google_stream_asr: [GOOGLE_ASR_STREAM] Starting streaming_recognize call
2025-12-27 22:24:20,473 [INFO] google_stream_asr: [GoogleStreamingASR] Stream started
2025-12-27 22:24:20,473 [WARNING] google_stream_asr: [ASR_STREAM_START] streaming_recognize started for call_id=unknown
2025-12-27 22:24:20,474 [WARNING] google_stream_asr: [ASR_STREAM_ITER] Starting to iterate responses
```

**結果**: ASRストリーミングは開始されている ✅

---

## 【ステップ3】Google ASR応答

### ログ

```
2025-12-27 22:24:20,474 [ERROR] google_stream_asr: [ASR_WORKER_EXCEPTION] Exception type=TypeError
2025-12-27 22:24:20,474 [ERROR] google_stream_asr: [ASR_WORKER_EXCEPTION] Exception message=SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:24:20,475 [ERROR] google_stream_asr: [GoogleStreamingASR] Recognition error: SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
```

**結果**: Google ASRがエラーで応答を返せていない ❌

**エラー詳細**:
- **エラー種類**: `TypeError`
- **エラーメッセージ**: `SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'`
- **発生箇所**: `/opt/libertycall/google_stream_asr.py`, line 118

---

## 【ステップ4】ASR初期化

### ログ

```
2025-12-27 22:24:20,472 [INFO] google_stream_asr: [GoogleStreamingASR] Initialized (language=ja-JP, sample_rate=16000)
2025-12-27 22:24:20,473 [WARNING] google_stream_asr: [ASR_STREAM_INIT] StreamingRecognitionConfig created: interim=False, single_utterance=False
```

**結果**: ASRは正常に初期化されている ✅

---

## 【ステップ5】feed_audio呼び出し

### ログ

```
2025-12-27 22:23:37,572 [WARNING] libertycall.gateway.ai_core: [ON_NEW_AUDIO_FEED] About to call feed_audio for call_id=in-2025122722230530, chunk_size=640
2025-12-27 22:23:37,572 [WARNING] libertycall.gateway.ai_core: [ON_NEW_AUDIO_FEED_DONE] feed_audio completed for call_id=in-2025122722230530
```

**結果**: `feed_audio` は正常に呼ばれている ✅

---

## 【ステップ6】ASRエラー

### ログ

```
2025-12-27 22:24:20,474 [ERROR] google_stream_asr: [ASR_WORKER_EXCEPTION] Exception type=TypeError
2025-12-27 22:24:20,474 [ERROR] google_stream_asr: [ASR_WORKER_EXCEPTION] Exception message=SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:24:20,475 [ERROR] google_stream_asr: [GoogleStreamingASR] Recognition error: SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
```

**結果**: ASR関連のエラーが発生している ❌

**エラー詳細**:
- **エラー種類**: `TypeError`
- **エラーメッセージ**: `SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'`
- **発生箇所**: `/opt/libertycall/google_stream_asr.py`, line 118
- **発生頻度**: 複数回発生（22:24:20, 22:24:56, 22:25:32, 22:26:08, 22:26:42）

---

## 【分析結果】

### 問題

**ASRがテキストを返さない原因**: Google Cloud Speech APIの `streaming_recognize()` メソッドの呼び出し方法が間違っている

### 原因

**`google_stream_asr.py` の118行目**:
```python
responses = self.client.streaming_recognize(request_gen())
```

**問題点**:
- `streaming_recognize()` メソッドの引数の形式が間違っている
- Google Cloud Speech API v1では、`streaming_recognize()` は `config` と `requests` の2つの引数を取る必要がある
- または、`requests` ジェネレータを直接渡すのではなく、正しい形式で渡す必要がある

**現在のコード**:
```python
# 118行目
responses = self.client.streaming_recognize(request_gen())
```

**正しい呼び出し方法**（推測）:
```python
# 方法1: configとrequestsを分けて渡す
responses = self.client.streaming_recognize(
    config=streaming_config,
    requests=request_gen()
)

# 方法2: requestsジェネレータのみを渡す（APIのバージョンによる）
responses = self.client.streaming_recognize(request_gen())
```

**エラーメッセージから推測**:
- `SpeechHelpers.streaming_recognize()` は `requests` という名前付き引数を期待している
- 現在のコードでは位置引数として渡しているため、エラーが発生している

### 修正案

**ファイル**: `/opt/libertycall/google_stream_asr.py`  
**行数**: 118行目

**修正方法1**（推奨）:
```python
# 修正前
responses = self.client.streaming_recognize(request_gen())

# 修正後
responses = self.client.streaming_recognize(requests=request_gen())
```

**修正方法2**（APIのバージョンによる）:
```python
# configとrequestsを分けて渡す
responses = self.client.streaming_recognize(
    config=streaming_config,
    requests=request_gen()
)
```

**確認が必要な事項**:
1. Google Cloud Speech APIのバージョン（v1, v1p1beta1など）
2. `streaming_recognize()` メソッドの正しいシグネチャ
3. `request_gen()` が返すジェネレータの形式

---

## 補足情報

### 現在の状況

1. **ASR有効化**: ✅ 環境変数は有効（`LC_ASR_STREAMING_ENABLED=1`）
2. **認証ファイル**: ✅ 存在する（`/opt/libertycall/config/google-credentials.json`）
3. **環境変数**: ❌ `GOOGLE_APPLICATION_CREDENTIALS` が未設定
4. **ASR初期化**: ✅ 正常に初期化されている
5. **音声受信**: ✅ `feed_audio` は正常に呼ばれている
6. **ASRストリーミング**: ✅ 開始されている
7. **Google ASR応答**: ❌ エラーで応答を返せていない

### エラーの影響

- ASRがテキストを返さない
- `on_transcript` が呼ばれない
- 再生処理が実行されない
- ユーザーの発話が認識されない

---

## 結論

**問題**: Google Cloud Speech APIの `streaming_recognize()` メソッドの呼び出し方法が間違っている

**原因**: `requests` 引数が名前付き引数として渡されていない

**修正案**: `google_stream_asr.py` の118行目を修正し、`requests=request_gen()` のように名前付き引数として渡す

**優先度**: 最優先（ASRが動作しないとシステムが機能しない）

