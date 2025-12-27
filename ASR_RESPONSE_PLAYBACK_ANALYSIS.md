# ASR応答が再生されない問題の分析レポート

**分析日時**: 2025-12-27 22:20  
**通話ID**: `in-2025122721375327`

---

## 【タスク1】stale session判定の場所

### grep結果

```bash
$ grep -n "stale session" /opt/libertycall -r --include="*.py"
/opt/libertycall/gateway/realtime_gateway.py:3260:                    f"[PLAYBACK] Skipping playback for stale session: call_id={call_id} "
```

**結果**: 
- **ファイル**: `/opt/libertycall/gateway/realtime_gateway.py`
- **行数**: 3260行目

---

## 【タスク2】判定条件

### コード（realtime_gateway.py 3246-3263行目）

```python
def _handle_playback(self, call_id: str, audio_file: str) -> None:
    """
    FreeSWITCHに音声再生リクエストを送信（ESL使用、自動リカバリ対応）
    """
    # 【修正3】古いセッションの強制クリーンアップ: アクティブなcall_idでない場合はスキップ
    if hasattr(self, '_active_calls') and self._active_calls:
        # UUIDとcall_id両方をチェック
        call_id_found = call_id in self._active_calls
        
        # call_uuid_mapでUUID→call_id変換も試す
        if not call_id_found and hasattr(self, 'call_uuid_map'):
            for mapped_call_id, mapped_uuid in self.call_uuid_map.items():
                if mapped_uuid == call_id and mapped_call_id in self._active_calls:
                    call_id_found = True
                    break
        
        if not call_id_found:
            self.logger.warning(
                f"[PLAYBACK] Skipping playback for stale session: call_id={call_id} "
                f"(not in active calls: {self._active_calls})"
            )
            return
```

**判定条件**:
1. `call_id in self._active_calls` が False
2. `call_uuid_map` でUUID→call_id変換を試すが、それでも見つからない
3. 上記のいずれにも該当しない場合、再生をスキップ

---

## 【タスク3】失敗理由の分析

### 初回アナウンスの呼び出し元

**初回アナウンス**: 
- **呼び出し元**: `freeswitch/scripts/play_audio_sequence.lua`
- **再生方法**: FreeSWITCHのLuaスクリプトから直接 `session:execute("playback", ...)` で再生
- **経路**: FreeSWITCH内部 → 直接再生（Pythonコードを経由しない）

```lua
-- play_audio_sequence.lua (105-107行目)
session:execute("playback", "/opt/libertycall/clients/000/audio/000.wav")
session:execute("playback", "/opt/libertycall/clients/000/audio/001.wav")
session:execute("playback", "/opt/libertycall/clients/000/audio/002.wav")
```

**重要な点**: 
- Luaスクリプトは `_handle_playback()` を経由しない
- `_active_calls` チェックを通過しない
- 直接FreeSWITCHセッションに再生コマンドを送信

### ASR応答の呼び出し元

**ASR応答**:
- **呼び出し元**: `ai_core.py` の `on_transcript()` メソッド
- **呼び出しフロー**:
  1. `on_transcript()` (3609行目)
  2. `_handle_flow_engine_transition()` (3957行目)
  3. `_play_template_sequence()` (1734行目)
  4. `playback_callback()` (1828行目) → `realtime_gateway.py._handle_playback()` (3239行目)
  5. **stale sessionチェック** (3246-3263行目) → **ここで失敗**

**重要な点**:
- Pythonコード経由で再生リクエストを送信
- `_handle_playback()` で `_active_calls` チェックを通過する必要がある
- しかし、`call_id` が `_active_calls` に存在しないため失敗

### 違いの説明

| 項目 | 初回アナウンス | ASR応答 |
|------|---------------|---------|
| **再生経路** | FreeSWITCH Luaスクリプト（直接） | Python → ESL → FreeSWITCH |
| **stale sessionチェック** | ❌ 通過しない（Luaスクリプト内） | ✅ 通過する必要がある |
| **`_active_calls` 依存** | ❌ 依存しない | ✅ 依存する |
| **成功/失敗** | ✅ 成功 | ❌ 失敗（stale session） |

**根本原因**:
- 初回アナウンスはFreeSWITCH内部で直接再生されるため、`_active_calls` チェックを通過しない
- ASR応答はPythonコード経由で再生されるため、`_active_calls` チェックを通過する必要がある
- しかし、ASR応答の時点で `call_id` が `_active_calls` に存在しない

---

## 【タスク4】修正案

### 問題の詳細

**ログ分析結果**:
- 通話開始時刻: 21:37:53
- `_active_calls` に追加された通話: `in-2025122721382807` (21:38:28)
- **問題の通話 `in-2025122721375327` は `_active_calls` に追加されていない**

**考えられる原因**:
1. 通話開始時に `_active_calls` に追加されていない
2. または、別の通話IDが追加されている（タイミングの問題）
3. RTPパケット受信時に追加されるはずだが、タイミングがずれている可能性

### 修正案1: stale sessionチェックを緩和（推奨）

**ファイル**: `/opt/libertycall/gateway/realtime_gateway.py`  
**行数**: 3246-3263行目

**修正内容**:
- `_active_calls` チェックを警告のみに変更（再生をスキップしない）
- または、`_active_calls` が空の場合はチェックをスキップ

**修正コード**:

```python
def _handle_playback(self, call_id: str, audio_file: str) -> None:
    """
    FreeSWITCHに音声再生リクエストを送信（ESL使用、自動リカバリ対応）
    """
    # 【修正】stale sessionチェックを警告のみに変更（再生は継続）
    if hasattr(self, '_active_calls') and self._active_calls:
        # UUIDとcall_id両方をチェック
        call_id_found = call_id in self._active_calls
        
        # call_uuid_mapでUUID→call_id変換も試す
        if not call_id_found and hasattr(self, 'call_uuid_map'):
            for mapped_call_id, mapped_uuid in self.call_uuid_map.items():
                if mapped_uuid == call_id and mapped_call_id in self._active_calls:
                    call_id_found = True
                    break
        
        if not call_id_found:
            # 警告のみ（再生は継続）
            self.logger.warning(
                f"[PLAYBACK] call_id={call_id} not in active_calls={self._active_calls}, "
                f"but continuing playback anyway (stale session check relaxed)"
            )
            # return を削除（再生を継続）
    
    # 以下、既存の再生処理を継続
    try:
        # ESL接続が切れている場合は自動リカバリを試みる
        ...
```

### 修正案2: `_active_calls` への追加を確実にする

**ファイル**: `/opt/libertycall/gateway/realtime_gateway.py`  
**行数**: 3239行目（`_handle_playback` の開始時）

**修正内容**:
- 再生リクエスト時に `call_id` が `_active_calls` に存在しない場合、自動的に追加

**修正コード**:

```python
def _handle_playback(self, call_id: str, audio_file: str) -> None:
    """
    FreeSWITCHに音声再生リクエストを送信（ESL使用、自動リカバリ対応）
    """
    # 【修正】call_idが_active_callsに存在しない場合は自動追加
    if hasattr(self, '_active_calls'):
        if not self._active_calls:
            self._active_calls = set()
        
        if call_id not in self._active_calls:
            # call_uuid_mapでUUID→call_id変換を試す
            call_id_found = False
            if hasattr(self, 'call_uuid_map'):
                for mapped_call_id, mapped_uuid in self.call_uuid_map.items():
                    if mapped_uuid == call_id and mapped_call_id in self._active_calls:
                        call_id_found = True
                        break
            
            if not call_id_found:
                # 自動追加（再生リクエストがあるということは通話がアクティブ）
                self.logger.warning(
                    f"[PLAYBACK] Auto-adding call_id={call_id} to _active_calls "
                    f"(playback request received but not in active_calls)"
                )
                self._active_calls.add(call_id)
    
    # 以下、既存の再生処理を継続
    try:
        # ESL接続が切れている場合は自動リカバリを試みる
        ...
```

### 推奨修正

**修正案2を推奨**します。理由：
1. より安全（再生リクエストがある = 通話がアクティブ）
2. `_active_calls` の整合性を保つ
3. タイミング問題を解決

---

## まとめ

### 問題の流れ

1. **通話開始** (21:37:53)
   - FreeSWITCH Luaスクリプトで初回アナウンス再生 ✅

2. **ASR認識** (21:38:48)
   - 「もしもし。」を認識 ✅
   - dialogue_flowでテンプレート004を選択 ✅

3. **再生リクエスト** (21:38:48)
   - `_play_template_sequence()` → `playback_callback()` → `_handle_playback()`
   - **stale sessionチェック**: `call_id` が `_active_calls` に存在しない ❌
   - **再生スキップ** ❌

4. **催促アナウンス** (21:39:04以降)
   - タイムアウト検出 → template_id=110送信試行
   - 同じく stale sessionチェックで失敗 ❌

### 修正の優先度

1. **最優先**: 修正案2（`_active_calls` への自動追加）
2. **次点**: 修正案1（stale sessionチェックの緩和）

