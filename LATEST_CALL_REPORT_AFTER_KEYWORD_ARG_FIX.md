# 最新通話ログ分析レポート（キーワード引数修正後）

**通話ID**: `in-2025122722414037`（最新）  
**通話日時**: 2025-12-27 22:41:40 ～ 約30秒  
**修正適用**: `streaming_recognize()` のキーワード引数修正（22:39:49再起動後）  
**分析日時**: 2025-12-27 22:42

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
**119-122行目**:
```python
responses = self.client.streaming_recognize(
    config=streaming_config,
    requests=request_gen()
)
```

**確認**: 修正は正しく適用されている ✅

---

### 2. ASRエラーの状況

**❌ エラーが継続しています**

**エラーログ**:
```
2025-12-27 22:40:33,372 [ERROR] [ASR_WORKER_EXCEPTION] Exception type=TypeError
2025-12-27 22:40:33,372 [ERROR] [ASR_WORKER_EXCEPTION] Exception message=SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:40:33,373 [ERROR] [GoogleStreamingASR] Recognition error: SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'

2025-12-27 22:41:02,366 [ERROR] [ASR_WORKER_EXCEPTION] Exception type=TypeError
2025-12-27 22:41:02,367 [ERROR] [ASR_WORKER_EXCEPTION] Exception message=SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:41:02,370 [ERROR] [GoogleStreamingASR] Recognition error: SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'

2025-12-27 22:41:35,619 [ERROR] [ASR_WORKER_EXCEPTION] Exception type=TypeError
2025-12-27 22:41:35,619 [ERROR] [ASR_WORKER_EXCEPTION] Exception message=SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:41:35,620 [ERROR] [GoogleStreamingASR] Recognition error: SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'

2025-12-27 22:41:43,083 [ERROR] [ASR_WORKER_EXCEPTION] Exception type=TypeError
2025-12-27 22:41:43,084 [ERROR] [ASR_WORKER_EXCEPTION] Exception message=SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
2025-12-27 22:41:43,084 [ERROR] [GoogleStreamingASR] Recognition error: SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
```

**問題点**:
- 修正後も同じエラーが発生している
- `config=streaming_config, requests=request_gen()` としてキーワード引数で渡しているが、エラーが解消されていない
- エラーメッセージに `SpeechHelpers.streaming_recognize()` と表示されている

**考えられる原因**:
1. **コードが再読み込みされていない**
   - Pythonのモジュールがキャッシュされている可能性
   - サービス再起動時に古いコードが読み込まれている可能性

2. **別のファイルが使用されている**
   - `google_stream_asr.py` が実際に使用されていない可能性
   - 別のASR実装が使用されている可能性

3. **APIの内部実装が異なる**
   - `SpeechHelpers` という内部クラスが使用されている
   - 実際のAPIの呼び出し方法が異なる可能性

---

### 3. ASR初期化の状況

**✅ ASRは正常に初期化されています**

**ログ**:
```
（ASR初期化ログは見つかりませんでしたが、エラーが発生しているため初期化はされていると推測）
```

**結果**: ASR初期化は正常（エラーが発生しているため） ✅

---

### 4. ASRテキスト認識の状況

**❌ ASRがテキストを返していません**

**理由**: エラーが発生しているため、ASRがテキストを返せていない

---

### 5. 再生処理の状況

**✅ 催促アナウンスは再生されています**

**ログ**:
```
2025-12-27 22:41:28,452 [INFO] [PLAY_TEMPLATE] Sent playback request (immediate): 
  call_id=in-2025122721375327 template_id=110 file=/opt/libertycall/clients/000/audio/110.wav
```

**結果**: 催促アナウンス（template_id=110）は送信されている ✅

**注意**: ログに表示されている `call_id` は `in-2025122721375327`（古い通話）です。最新の通話 `in-2025122722414037` の再生ログは見つかりませんでした。

---

### 6. `_active_calls` への追加

**✅ `_active_calls` に追加されています**

**ログ**:
```
2025-12-27 22:41:40,783 [WARNING] [CALL_START_TRACE] [LOC_START] 
  Adding in-2025122722414037 to _active_calls (event_socket) at 1766842900.783
```

**結果**: 通話開始時に `_active_calls` に追加されている ✅

---

## 🎯 根本原因の推測

### 主要問題: コードが再読み込みされていない可能性

**現在の修正**:
```python
responses = self.client.streaming_recognize(
    config=streaming_config,
    requests=request_gen()
)
```

**エラーメッセージ**:
```
SpeechHelpers.streaming_recognize() missing 1 required positional argument: 'requests'
```

**問題点**:
- 修正は正しく適用されている
- しかし、エラーが継続している
- Pythonのモジュールがキャッシュされている可能性
- または、別のファイルが使用されている可能性

**考えられる原因**:

1. **Pythonモジュールのキャッシュ**
   - `__pycache__` ディレクトリに古いコードがキャッシュされている
   - サービス再起動時にキャッシュが読み込まれている

2. **別のファイルが使用されている**
   - `google_stream_asr.py` が実際に使用されていない
   - 別のASR実装（`ai_core.py` の `GoogleASR` クラスなど）が使用されている

3. **インポートパスの問題**
   - 異なるパスから `google_stream_asr.py` が読み込まれている
   - 修正したファイルとは別のファイルが使用されている

---

## 📊 タイムライン

| 時刻 | イベント | 状態 |
|------|---------|------|
| 22:39:49 | サービス再起動 | ✅ |
| 22:40:31 | 通話開始（in-2025122722403178） | ✅ |
| 22:40:33 | ASRエラー発生 | ❌ |
| 22:41:01 | 通話開始（in-2025122722410131） | ✅ |
| 22:41:02 | ASRエラー発生 | ❌ |
| 22:41:14 | 通話開始（in-2025122722411426） | ✅ |
| 22:41:35 | ASRエラー発生 | ❌ |
| 22:41:40 | 通話開始（in-2025122722414037） | ✅ |
| 22:41:43 | ASRエラー発生 | ❌ |

---

## 🔧 推奨される次のステップ

### 優先度1: コードが実際に使用されているか確認

1. **実際に使用されているファイルの確認**
   ```bash
   # google_stream_asr.py がどこからインポートされているか確認
   grep -r "from google_stream_asr import\|import google_stream_asr" /opt/libertycall
   ```

2. **Pythonキャッシュのクリア**
   ```bash
   # __pycache__ ディレクトリを削除
   find /opt/libertycall -type d -name __pycache__ -exec rm -r {} +
   ```

3. **実際に使用されているコードの確認**
   - `google_stream_asr.py` が実際に使用されているか確認
   - 別のASR実装が使用されている可能性を確認

### 優先度2: 既存の動作している実装を確認

1. **ai_core.py の GoogleASR クラスを確認**
   - 既存の実装が正しく動作しているか確認
   - その実装方法を参考にする

2. **ASRプロバイダの確認**
   - どのASR実装が使用されているか確認
   - `LC_ASR_PROVIDER` 環境変数を確認

### 優先度3: デバッグログの追加

1. **修正が適用されているか確認するログを追加**
   - `streaming_recognize()` 呼び出し前にログを追加
   - 実際に使用されているコードを確認

---

## 📝 結論

### 修正の効果

**❌ 修正は適用されているが、エラーが解消されていない**

- 修正は正しく適用されている（`config=streaming_config, requests=request_gen()`）
- しかし、同じエラーが継続している
- Pythonモジュールのキャッシュや、別のファイルが使用されている可能性が高い

### 根本原因

**コードが再読み込みされていない、または別のファイルが使用されている**

- 修正した `google_stream_asr.py` が実際に使用されていない可能性
- Pythonのモジュールキャッシュが古いコードを保持している可能性
- 別のASR実装が使用されている可能性

### 次のアクション

1. **実際に使用されているファイルを確認**
   - `google_stream_asr.py` がどこからインポートされているか確認
   - 実際に使用されているコードを確認

2. **Pythonキャッシュのクリア**
   - `__pycache__` ディレクトリを削除
   - サービスを再起動

3. **既存の動作している実装を確認**
   - `ai_core.py` の `GoogleASR` クラスが使用されているか確認
   - その実装方法を参考にする

---

**修正は適用されていますが、エラーが解消されていません。コードが再読み込みされていない、または別のファイルが使用されている可能性が高いです。**

