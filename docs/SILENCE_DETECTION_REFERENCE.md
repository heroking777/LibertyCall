# 無音検出関連箇所の完全リファレンス

## 主要な関数

### 1. `_no_input_monitor_loop()` - 2224行目
無音状態を監視し、自動ハングアップを行うメインループ

```2224:2317:/opt/libertycall/gateway/realtime_gateway.py
    async def _no_input_monitor_loop(self):
        """無音状態を監視し、自動ハングアップを行う"""
        self.logger.info("NO_INPUT_MONITOR_LOOP: started")
        
        while self.running:
            try:
                now = time.monotonic()
                
                # _active_calls が存在しない場合は初期化
                if not hasattr(self, '_active_calls'):
                    self._active_calls = set()
                
                # 現在アクティブな通話を走査
                active_call_ids = list(self._active_calls) if self._active_calls else []
                
                # アクティブな通話がない場合は待機
                if not active_call_ids:
                    await asyncio.sleep(1.0)
                    continue
                
                # 各アクティブな通話について無音検出を実行
                for call_id in active_call_ids:
                    try:
                        # 最後に有音を検出した時刻を取得
                        last_voice = self._last_voice_time.get(call_id, 0)
                        
                        # 最後に有音を検出した時刻が0の場合は、TTS送信完了時刻を使用
                        if last_voice == 0:
                            last_voice = self._last_tts_end_time.get(call_id, now)
                        
                        # 無音継続時間を計算
                        elapsed = now - last_voice
                        
                        # TTS送信中は無音検出をスキップ
                        if self.is_speaking_tts:
                            continue
                        
                        # 初回シーケンス再生中は無音検出をスキップ
                        if self.initial_sequence_playing:
                            continue
                        
                        # 無音5秒ごとに警告ログ出力
                        if elapsed > 5 and abs(elapsed % 5) < 1:
                            self.logger.warning(
                                f"[SILENCE DETECTED] {elapsed:.1f}s of silence call_id={call_id}"
                            )
                        
                        # 警告送信済みセットを初期化（存在しない場合）
                        if call_id not in self._silence_warning_sent:
                            self._silence_warning_sent[call_id] = set()
                        
                        warnings = self._silence_warning_sent[call_id]
                        
                        # 段階的な無音警告（5秒、10秒、15秒）とアナウンス再生
                        if elapsed >= 5.0 and 5.0 not in warnings:
                            warnings.add(5.0)
                            self.logger.warning(f"[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}")
                            await self._play_silence_warning(call_id, 5.0)
                        elif elapsed >= 10.0 and 10.0 not in warnings:
                            warnings.add(10.0)
                            self.logger.warning(f"[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}")
                            await self._play_silence_warning(call_id, 10.0)
                        elif elapsed >= 15.0 and 15.0 not in warnings:
                            warnings.add(15.0)
                            self.logger.warning(f"[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}")
                            await self._play_silence_warning(call_id, 15.0)
                        
                        # 無音が規定時間を超えたら強制切断
                        max_silence_time = getattr(self, "SILENCE_HANGUP_TIME", 20.0)
                        if elapsed > max_silence_time:
                            self.logger.warning(
                                f"[AUTO-HANGUP] Silence limit exceeded ({elapsed:.1f}s) call_id={call_id}"
                            )
                            try:
                                # 非同期タスクとして実行（既存の同期関数を呼び出す）
                                loop = asyncio.get_running_loop()
                                loop.run_in_executor(None, self._handle_hangup, call_id)
                            except Exception as e:
                                self.logger.exception(f"[AUTO-HANGUP] Hangup failed call_id={call_id} error={e}")
                            # 警告セットをクリア（次の通話のために）
                            self._silence_warning_sent.pop(call_id, None)
                            continue
                        
                        # 音声が検出された場合は警告セットをリセット
                        if elapsed < 1.0:  # 1秒以内に音声が検出された場合
                            if call_id in self._silence_warning_sent:
                                self._silence_warning_sent[call_id].clear()
                    except Exception as e:
                        self.logger.exception(f"NO_INPUT_MONITOR_LOOP error for call_id={call_id}: {e}")
                
            except Exception as e:
                self.logger.exception(f"NO_INPUT_MONITOR_LOOP error: {e}")
            
            await asyncio.sleep(1.0)  # 1秒間隔でチェック
```

**ログ出力箇所:**
- 2266-2269行目: `[SILENCE DETECTED] {elapsed:.1f}s of silence call_id={call_id}` (5秒ごと)
- 2280行目: `[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}` (5秒時点)
- 2284行目: `[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}` (10秒時点)
- 2288行目: `[SILENCE DETECTED] {elapsed:.1f}s of silence for call_id={call_id}` (15秒時点)
- 2294-2295行目: `[AUTO-HANGUP] Silence limit exceeded ({elapsed:.1f}s) call_id={call_id}` (20秒時点)

**DB/ログ記録:**
- ❌ この関数内では直接記録していない
- ✅ `_handle_hangup()` を呼び出して記録処理を委譲

---

### 2. `_handle_hangup()` - 1612行目
自動切断処理を実行（console_bridge に切断を記録、Asterisk に hangup を指示）

```1612:1701:/opt/libertycall/gateway/realtime_gateway.py
    def _handle_hangup(self, call_id: str) -> None:
        """
        自動切断処理を実行
        - console_bridge に切断を記録
        - Asterisk に hangup を指示
        """
        # 発信者番号を取得（ログ出力用）
        caller_number = getattr(self.ai_core, "caller_number", None) or "未設定"
        
        self.logger.debug(f"[FORCE_HANGUP] HANGUP_REQUEST: call_id={call_id} self.call_id={self.call_id} caller={caller_number}")
        self.logger.info(
            f"[FORCE_HANGUP] HANGUP_REQUEST: call_id={call_id} self.call_id={self.call_id} caller={caller_number}"
        )
        
        # call_id が未設定の場合はパラメータから設定
        if not self.call_id and call_id:
            self.call_id = call_id
            self.logger.info(
                f"[FORCE_HANGUP] HANGUP_REQUEST: set self.call_id={call_id} from parameter caller={caller_number}"
            )
        
        if not self.call_id:
            self.logger.warning(
                f"[FORCE_HANGUP] HANGUP_REQUEST_SKIP: call_id={call_id} caller={caller_number} reason=no_self_call_id"
            )
            return
        
        # 無音経過時間をログに記録
        elapsed = self._no_input_elapsed.get(self.call_id, 0.0)
        no_input_streak = 0
        state = self.ai_core._get_session_state(self.call_id)
        if state:
            no_input_streak = state.no_input_streak
        
        self.logger.warning(
            f"[FORCE_HANGUP] Disconnecting call_id={self.call_id} caller={caller_number} "
            f"after {elapsed:.1f}s of silence (streak={no_input_streak}, MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s)"
        )
        
        # 録音を停止
        self._stop_recording()
        
        # console_bridge に切断を記録
        if self.console_bridge.enabled:
            self.console_bridge.complete_call(self.call_id, ended_at=datetime.utcnow())
            self.logger.info(
                f"[FORCE_HANGUP] console_bridge marked hangup call_id={self.call_id} caller={caller_number}"
            )
        
        # 通話終了時の状態クリーンアップ
        call_id_to_cleanup = self.call_id or call_id
        if call_id_to_cleanup:
            if hasattr(self, '_active_calls'):
                self._active_calls.discard(call_id_to_cleanup)
            self._last_voice_time.pop(call_id_to_cleanup, None)
            self._last_silence_time.pop(call_id_to_cleanup, None)
            self._last_tts_end_time.pop(call_id_to_cleanup, None)
            self._last_user_input_time.pop(call_id_to_cleanup, None)
            self._silence_warning_sent.pop(call_id_to_cleanup, None)
            if hasattr(self, '_initial_tts_sent'):
                self._initial_tts_sent.discard(call_id_to_cleanup)
            self.logger.debug(f"[CALL_CLEANUP] Cleared state for call_id={call_id_to_cleanup}")
        
        # Asterisk に hangup を依頼（非同期で実行）
        try:
            try:
                project_root = _PROJECT_ROOT  # 既存の定義を優先
            except NameError:
                project_root = "/opt/libertycall"
            script_path = os.path.join(project_root, "scripts", "hangup_call.py")
            self.logger.info(
                f"[FORCE_HANGUP] HANGUP_REQUEST: Spawning hangup_call script_path={script_path} call_id={self.call_id} caller={caller_number}"
            )
            proc = subprocess.Popen(
                [sys.executable, script_path, self.call_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.logger.info(
                f"[FORCE_HANGUP] HANGUP_REQUEST: hangup_call spawned pid={proc.pid} call_id={self.call_id} caller={caller_number}"
            )
        except Exception as e:
            self.logger.exception(
                f"[FORCE_HANGUP] HANGUP_REQUEST_FAILED: Failed to spawn hangup_call call_id={self.call_id} caller={caller_number} error={e!r}"
            )
        
        self.logger.info(
            "HANGUP_REQUEST_DONE: call_id=%s",
            self.call_id
        )
```

**ログ出力箇所:**
- 1621-1624行目: `[FORCE_HANGUP] HANGUP_REQUEST: call_id={call_id} ...`
- 1646-1649行目: `[FORCE_HANGUP] Disconnecting call_id={self.call_id} caller={caller_number} after {elapsed:.1f}s of silence ...`
- 1657-1659行目: `[FORCE_HANGUP] console_bridge marked hangup call_id={self.call_id} caller={caller_number}`
- 1682-1684行目: `[FORCE_HANGUP] HANGUP_REQUEST: Spawning hangup_call ...`
- 1690-1692行目: `[FORCE_HANGUP] HANGUP_REQUEST: hangup_call spawned pid={proc.pid} ...`
- 1698-1701行目: `HANGUP_REQUEST_DONE: call_id={self.call_id}`

**DB/ログ記録:**
- ✅ 1656行目: `self.console_bridge.complete_call(self.call_id, ended_at=datetime.utcnow())` - console_bridge経由でDBに記録

---

### 3. `_play_silence_warning()` - 2327行目
無音時に流すアナウンス

```2327:2346:/opt/libertycall/gateway/realtime_gateway.py
    async def _play_silence_warning(self, call_id: str, warning_interval: float):
        """
        無音時に流すアナウンス
        
        :param call_id: 通話ID
        :param warning_interval: 警告間隔（5.0, 10.0, 15.0）
        """
        try:
            # 警告間隔に応じてメッセージを変更
            text_map = {
                5.0: "もしもし？お話がない場合は通話を終了します。",
                10.0: "もしもし？お聞き取りできていますか？",
                15.0: "お話がない場合は、まもなく通話を終了します。"
            }
            text = text_map.get(warning_interval, "もしもし？お話がない場合は通話を終了します。")
            
            self.logger.info(f"[SILENCE_WARNING] call_id={call_id} interval={warning_interval:.0f}s text={text!r}")
            await self._play_tts(call_id, text)
        except Exception as e:
            self.logger.error(f"Silence warning playback failed for call_id={call_id}: {e}", exc_info=True)
```

**ログ出力箇所:**
- 2343行目: `[SILENCE_WARNING] call_id={call_id} interval={warning_interval:.0f}s text={text!r}`

**DB/ログ記録:**
- ❌ この関数内では直接記録していない

---

### 4. `_handle_no_input_timeout()` - 2357行目
無音タイムアウトを処理: NOT_HEARD intentをai_coreに渡す

```2357:2449:/opt/libertycall/gateway/realtime_gateway.py
    async def _handle_no_input_timeout(self, call_id: str):
        """
        無音タイムアウトを処理: NOT_HEARD intentをai_coreに渡す
        
        :param call_id: 通話ID
        """
        try:
            # 【デバッグ】無音タイムアウト発火
            state = self.ai_core._get_session_state(call_id)
            streak_before = state.no_input_streak
            streak = min(streak_before + 1, self.NO_INPUT_STREAK_LIMIT)
            
            # 明示的なデバッグログを追加
            self.logger.debug(f"[NO_INPUT] Triggered for call_id={call_id}, streak={streak}")
            self.logger.info(f"[NO_INPUT] Triggered for call_id={call_id}, streak={streak}")
            
            # 発信者番号を取得（ログ出力用）
            caller_number = getattr(self.ai_core, "caller_number", None) or "未設定"
            self.logger.debug(f"[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}")
            self.logger.info(
                f"[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}"
            )
            
            # ai_coreの状態を取得
            no_input_streak = streak
            state.no_input_streak = no_input_streak
            # 無音経過時間を累積
            elapsed = self._no_input_elapsed.get(call_id, 0.0) + self.NO_INPUT_TIMEOUT
            self._no_input_elapsed[call_id] = elapsed
            
            self.logger.debug(f"[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} elapsed={elapsed:.1f}s (incrementing)")
            self.logger.info(
                f"[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} elapsed={elapsed:.1f}s (incrementing)"
            )
            
            # NOT_HEARD intentとして処理（空のテキストで呼び出す）
            # ai_core側でno_input_streakに基づいてテンプレートを選択する
            reply_text = self.ai_core.on_transcript(call_id, "", is_final=True)
            
            if reply_text:
                # TTS送信（テンプレートIDはai_core側で決定される）
                template_ids = state.last_ai_templates if hasattr(state, 'last_ai_templates') else []
                self._send_tts(call_id, reply_text, template_ids, False)
                
                # テンプレート112の場合は自動切断を予約（ai_core側で処理される）
                if "112" in template_ids:
                    self.logger.info(
                        f"[NO_INPUT] call_id={call_id} template=112 detected, auto_hangup will be scheduled"
                    )
            
            # 最大無音時間を超えた場合は強制切断を実行（管理画面でも把握しやすいよう詳細ログ）
            if self._no_input_elapsed.get(call_id, 0.0) >= self.MAX_NO_INPUT_TIME:
                elapsed_total = self._no_input_elapsed.get(call_id, 0.0)
                self.logger.debug(
                    f"[NO_INPUT] call_id={call_id} caller={caller_number} exceeded MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s "
                    f"(streak={no_input_streak}, elapsed={elapsed_total:.1f}s) -> FORCE_HANGUP"
                )
                self.logger.warning(
                    f"[NO_INPUT] call_id={call_id} caller={caller_number} exceeded MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s "
                    f"(streak={no_input_streak}, elapsed={elapsed_total:.1f}s) -> FORCE_HANGUP"
                )
                # 直前の状態を詳細ログに出力（原因追跡用）
                self.logger.debug(
                    f"[FORCE_HANGUP] Preparing disconnect: call_id={call_id} caller={caller_number} "
                    f"elapsed={elapsed_total:.1f}s streak={no_input_streak} max_timeout={self.MAX_NO_INPUT_TIME}s"
                )
                self.logger.warning(
                    f"[FORCE_HANGUP] Preparing disconnect: call_id={call_id} caller={caller_number} "
                    f"elapsed={elapsed_total:.1f}s streak={no_input_streak} max_timeout={self.MAX_NO_INPUT_TIME}s"
                )
                self.logger.debug(
                    f"[FORCE_HANGUP] Attempting to disconnect call_id={call_id} after {elapsed_total:.1f}s of silence "
                    f"(streak={no_input_streak}, timeout={self.MAX_NO_INPUT_TIME}s)"
                )
                self.logger.info(
                    f"[FORCE_HANGUP] Attempting to disconnect call_id={call_id} after {elapsed_total:.1f}s of silence "
                    f"(streak={no_input_streak}, timeout={self.MAX_NO_INPUT_TIME}s)"
                )
                # 1分無音継続時は強制切断をスケジュール（確実に実行）
                try:
                    if hasattr(self.ai_core, "_schedule_auto_hangup"):
                        self.ai_core._schedule_auto_hangup(call_id, delay_sec=1.0)
                        self.logger.info(
                            f"[NO_INPUT] FORCE_HANGUP_SCHEDULED: call_id={call_id} caller={caller_number} "
                            f"elapsed={elapsed_total:.1f}s delay=1.0s"
                        )
                    elif self.ai_core.hangup_callback:
                        # _schedule_auto_hangupが存在しない場合は直接コールバックを呼び出す
                        self.logger.info(
                            f"[NO_INPUT] FORCE_HANGUP_DIRECT: call_id={call_id} caller={caller_number} "
                            f"elapsed={elapsed_total:.1f}s (no _schedule_auto_hangup method)"
                        )
                        self.ai_core.hangup_callback(call_id)
```

**ログ出力箇所:**
- 2371行目: `[NO_INPUT] Triggered for call_id={call_id}, streak={streak}`
- 2376-2378行目: `[NO_INPUT] Handling timeout for call_id={call_id} caller={caller_number}`
- 2388-2390行目: `[NO_INPUT] call_id={call_id} caller={caller_number} streak={no_input_streak} elapsed={elapsed:.1f}s (incrementing)`
- 2403-2405行目: `[NO_INPUT] call_id={call_id} template=112 detected, auto_hangup will be scheduled`
- 2414-2417行目: `[NO_INPUT] call_id={call_id} caller={caller_number} exceeded MAX_NO_INPUT_TIME={self.MAX_NO_INPUT_TIME}s ... -> FORCE_HANGUP`
- 2423-2426行目: `[FORCE_HANGUP] Preparing disconnect: call_id={call_id} caller={caller_number} ...`
- 2431-2434行目: `[FORCE_HANGUP] Attempting to disconnect call_id={call_id} after {elapsed_total:.1f}s of silence ...`
- 2439-2442行目: `[NO_INPUT] FORCE_HANGUP_SCHEDULED: call_id={call_id} caller={caller_number} ...`
- 2445-2448行目: `[NO_INPUT] FORCE_HANGUP_DIRECT: call_id={call_id} caller={caller_number} ...`

**DB/ログ記録:**
- ❌ この関数内では直接記録していない
- ✅ `hangup_callback` 経由で `_handle_hangup()` を呼び出して記録処理を委譲

---

### 5. `_start_no_input_timer()` - 2185行目
無音検知タイマーを起動する

```2185:2222:/opt/libertycall/gateway/realtime_gateway.py
    async def _start_no_input_timer(self, call_id: str) -> None:
        """
        無音検知タイマーを起動する（async対応版、既存タスクがあればキャンセルして再起動）
        """
        try:
            existing = self._no_input_timers.pop(call_id, None)
            if existing and not existing.done():
                existing.cancel()
                self.logger.debug(f"[DEBUG_INIT] Cancelled existing no_input_timer for call_id={call_id}")

            now = time.monotonic()
            self._last_user_input_time[call_id] = now
            self._last_tts_end_time[call_id] = now
            self._no_input_elapsed[call_id] = 0.0

            async def _timer():
                try:
                    await asyncio.sleep(self.NO_INPUT_TIMEOUT)
                    if not self.running:
                        return
                    await self._handle_no_input_timeout(call_id)
                except asyncio.CancelledError:
                    self.logger.debug(f"[DEBUG_INIT] no_input_timer cancelled for call_id={call_id}")
                finally:
                    self._no_input_timers.pop(call_id, None)

            task = asyncio.create_task(_timer())
            self._no_input_timers[call_id] = task
            self.logger.debug(
                f"[DEBUG_INIT] no_input_timer started for call_id={call_id} "
                f"(timeout={self.NO_INPUT_TIMEOUT}s, task={task}, done={task.done()}, cancelled={task.cancelled()})"
            )
            self.logger.info(
                f"[DEBUG_INIT] no_input_timer started for call_id={call_id} "
                f"(timeout={self.NO_INPUT_TIMEOUT}s, task_done={task.done()}, task_cancelled={task.cancelled()})"
            )
        except Exception as e:
            self.logger.exception(f"[NO_INPUT] Failed to start no_input_timer for call_id={call_id}: {e}")
```

**ログ出力箇所:**
- 2217-2220行目: `[DEBUG_INIT] no_input_timer started for call_id={call_id} ...`

**DB/ログ記録:**
- ❌ この関数内では直接記録していない

---

## ログ出力箇所のまとめ

### `[SILENCE DETECTED]` ログ
- 2266-2269行目: 5秒ごとの警告ログ（`_no_input_monitor_loop()`）
- 2280行目: 5秒時点の警告（`_no_input_monitor_loop()`）
- 2284行目: 10秒時点の警告（`_no_input_monitor_loop()`）
- 2288行目: 15秒時点の警告（`_no_input_monitor_loop()`）

### `[AUTO-HANGUP]` ログ
- 2294-2295行目: 20秒時点の自動切断（`_no_input_monitor_loop()`）

### `[FORCE_HANGUP]` ログ
- 1621-1624行目: ハングアップ要求開始（`_handle_hangup()`）
- 1646-1649行目: 切断実行（`_handle_hangup()`）
- 2414-2417行目: MAX_NO_INPUT_TIME超過（`_handle_no_input_timeout()`）
- 2423-2426行目: 切断準備（`_handle_no_input_timeout()`）
- 2431-2434行目: 切断試行（`_handle_no_input_timeout()`）

### `[NO_INPUT]` ログ
- 2371行目: タイムアウト発火（`_handle_no_input_timeout()`）
- 2376-2378行目: タイムアウト処理開始（`_handle_no_input_timeout()`）
- 2388-2390行目: 無音経過時間の累積（`_handle_no_input_timeout()`）

### `[SILENCE_WARNING]` ログ
- 2343行目: 無音警告アナウンス再生（`_play_silence_warning()`）

---

## DB/ログ記録のまとめ

### ✅ 記録されている箇所
- **1656行目**: `self.console_bridge.complete_call(self.call_id, ended_at=datetime.utcnow())` - `_handle_hangup()` 内
  - console_bridge経由でDBに記録
  - ログ: `[FORCE_HANGUP] console_bridge marked hangup call_id={self.call_id} caller={caller_number}`

### ❌ 記録されていない箇所
- `[SILENCE DETECTED]` ログ出力時（2266-2289行目）
- `[AUTO-HANGUP]` ログ出力時（2294-2295行目）
- `[NO_INPUT]` ログ出力時（2371-2390行目）
- `[SILENCE_WARNING]` ログ出力時（2343行目）

**注意**: これらのログは標準ログファイル（`systemd_gateway_stdout.log`）には出力されますが、DBや専用のhangup_logファイルには記録されていません。

