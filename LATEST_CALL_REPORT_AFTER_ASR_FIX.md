# 最新通話ログ分析レポート（ASR修正後）

**通話ID**: `in-2025122722301011`  
**通話日時**: 2025-12-27 22:30:10 ～ 約30秒  
**修正適用**: `streaming_recognize()` の呼び出し修正（22:29:27再起動後）  
**分析日時**: 2025-12-27 22:32

---

## 📋 通話概要

### 観察された現象
- ✅ **初回アナウンス**: 再生される
- ❌ **ASR反応**: なし（エラーが継続）
- ✅ **催促アナウンス**: 再生される
- ⏱️ **通話時間**: 約30秒

---

## 🔍 詳細分析

### 1. 修正の確認

**✅ 修正は正しく適用されています**

**ファイル**: `/opt/libertycall/google_stream_asr.py`  
**118行目**:
```python
responses = self.client.streaming_recognize(requests=request_gen())
```

**確認**: 修正は正しく適用されている ✅

---

### 2. ASRエラーの状況

**❌ エラーが継続しています**

**エラーログ**:
```
2025-12-27 22:30:08,059 [ERROR] google_stream_asr: [GoogleStreamingASR] Recognition error: 
  SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:30:11,563 [ERROR] google_stream_asr: [GoogleStreamingASR] Recognition error: 
  SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
```

**問題点**:
- 修正後も同じエラーが発生している
- `requests=request_gen()` として名前付き引数で渡しているが、エラーが解消されていない
- エラーメッセージに `SpeechHelpers.streaming_recognize()` と表示されている

**考えられる原因**:
1. **APIのバージョンが異なる**
   - Google Cloud Speech APIのバージョンによって、呼び出し方法が異なる可能性
   - `SpeechHelpers` という内部クラスが使用されている

2. **メソッドシグネチャの違い**
   - `streaming_recognize()` の正しいシグネチャが異なる可能性
   - 位置引数と名前付き引数の組み合わせが間違っている可能性

3. **Pythonパッケージのバージョン**
   - `google-cloud-speech` パッケージのバージョンによって、APIが異なる可能性

---

### 3. ASR初期化の状況

**✅ ASRは正常に初期化されています**

**ログ**:
```
2025-12-27 22:30:08,056 [INFO] google_stream_asr: [GoogleStreamingASR] Initialized (language=ja-JP, sample_rate=16000)
2025-12-27 22:30:08,056 [WARNING] google_stream_asr: [ASR_STREAM_INIT] StreamingRecognitionConfig created: interim=False, single_utterance=False
2025-12-27 22:30:08,057 [INFO] google_stream_asr: [GOOGLE_ASR_STREAM] Starting streaming_recognize call
2025-12-27 22:30:08,057 [INFO] google_stream_asr: [GoogleStreamingASR] Stream started
```

**結果**: ASR初期化は正常 ✅

---

### 4. ASRテキスト認識の状況

**❌ ASRがテキストを返していません**

**ログ**:
```
2025-12-27 22:30:22,006 [INFO] libertycall.gateway.ai_core: [ASR_TRANSCRIPT] on_transcript called: 
  call_id=in-2025122722301011 is_final=True text='' text_length=0 text_stripped=''
```

**問題点**:
- `on_transcript` は呼ばれているが、テキストが空（`text=''`）
- エラーが発生しているため、ASRがテキストを返せていない

---

### 5. 再生処理の状況

**✅ 催促アナウンスは再生されています**

**ログ**:
```
2025-12-27 22:30:17,569 [INFO] libertycall.gateway.ai_core: [PLAY_TEMPLATE] Sent playback request (immediate): 
  call_id=in-2025122721375327 template_id=110 file=/opt/libertycall/clients/000/audio/110.wav
```

**結果**: 催促アナウンス（template_id=110）は送信されている ✅

**注意**: ログに表示されている `call_id` は `in-2025122721375327`（古い通話）です。最新の通話 `in-2025122722301011` の再生ログは見つかりませんでした。

---

### 6. `_active_calls` への追加

**✅ `_active_calls` に追加されています**

**ログ**:
```
2025-12-27 22:30:10,948 [WARNING] __main__: [CALL_START_TRACE] [LOC_START] 
  Adding in-2025122722301011 to _active_calls (event_socket) at 1766842210.949
```

**結果**: 通話開始時に `_active_calls` に追加されている ✅

---

## 🎯 根本原因の推測

### 主要問題: Google Cloud Speech APIの呼び出し方法が間違っている

**現在の修正**:
```python
responses = self.client.streaming_recognize(requests=request_gen())
```

**エラーメッセージ**:
```
SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
```

**考えられる原因**:

1. **APIのバージョンが異なる**
   - Google Cloud Speech API v1とv1p1beta1で、呼び出し方法が異なる可能性
   - `SpeechHelpers` という内部クラスが使用されている

2. **メソッドシグネチャの違い**
   - `streaming_recognize()` は位置引数として `config` と `requests` を期待している可能性
   - または、`config` を別途渡す必要がある可能性

3. **Pythonパッケージのバージョン**
   - `google-cloud-speech` パッケージのバージョンによって、APIが異なる可能性

---

## 📊 タイムライン

| 時刻 | イベント | 状態 |
|------|---------|------|
| 22:30:08 | ASR初期化 | ✅ |
| 22:30:08 | streaming_recognize呼び出し | ❌ エラー発生 |
| 22:30:10 | 通話開始 | ✅ |
| 22:30:10 | `_active_calls` に追加 | ✅ |
| 22:30:11 | ASR再初期化 | ✅ |
| 22:30:11 | streaming_recognize呼び出し | ❌ エラー発生 |
| 22:30:22 | on_transcript呼び出し（空テキスト） | ❌ |
| 22:30:17 | 催促アナウンス送信 | ✅ |

---

## 🔧 推奨される次のステップ

### 優先度1: Google Cloud Speech APIの正しい呼び出し方法を確認

1. **APIバージョンの確認**
   ```bash
   pip show google-cloud-speech
   ```

2. **正しい呼び出し方法の確認**
   - Google Cloud Speech APIのドキュメントを確認
   - 使用しているAPIバージョン（v1, v1p1beta1など）を確認
   - 正しいメソッドシグネチャを確認

3. **代替呼び出し方法の試行**
   ```python
   # 方法1: configとrequestsを分けて渡す
   responses = self.client.streaming_recognize(
       config=streaming_config,
       requests=request_gen()
   )
   
   # 方法2: 位置引数として渡す
   responses = self.client.streaming_recognize(
       streaming_config,
       request_gen()
   )
   ```

### 優先度2: パッケージバージョンの確認

1. **インストールされているパッケージの確認**
   ```bash
   pip list | grep google-cloud-speech
   ```

2. **最新バージョンへの更新**
   ```bash
   pip install --upgrade google-cloud-speech
   ```

### 優先度3: コードの確認

1. **他のASR実装の確認**
   - `ai_core.py` の `GoogleASR` クラスの実装を確認
   - 正しい呼び出し方法を参考にする

---

## 📝 結論

### 修正の効果

**❌ 修正は適用されているが、エラーが解消されていない**

- 修正は正しく適用されている（`requests=request_gen()`）
- しかし、同じエラーが継続している
- Google Cloud Speech APIの呼び出し方法が間違っている可能性が高い

### 根本原因

**Google Cloud Speech APIの呼び出し方法が間違っている**

- `streaming_recognize()` メソッドの正しいシグネチャが異なる可能性
- APIのバージョンやパッケージのバージョンによって、呼び出し方法が異なる可能性

### 次のアクション

1. **Google Cloud Speech APIのドキュメントを確認**
   - 使用しているAPIバージョンを確認
   - 正しいメソッドシグネチャを確認

2. **パッケージバージョンの確認**
   - `google-cloud-speech` パッケージのバージョンを確認
   - 必要に応じて更新

3. **代替呼び出し方法の試行**
   - `config` と `requests` を分けて渡す方法を試す
   - 位置引数として渡す方法を試す

---

**修正は適用されていますが、エラーが解消されていません。Google Cloud Speech APIの正しい呼び出し方法を確認する必要があります。**

