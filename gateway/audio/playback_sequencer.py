"""Initial playback sequencing utilities."""
from __future__ import annotations

import asyncio
import time
import traceback
import wave
import audioop
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from libertycall.gateway.audio.playback_manager import GatewayPlaybackManager


_CURRENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _CURRENT_DIR.parent.parent


class PlaybackSequencer:
    def __init__(self, manager: "GatewayPlaybackManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    async def queue_initial_audio_sequence(self, client_id: Optional[str]) -> None:
        manager = self.manager
        # ★関数の最初でログ★
        self.logger.warning("[INIT_METHOD_ENTRY] Called with client_id=%s", client_id)
        try:
            # 【追加】タスク開始ログ
            self.logger.warning("[INIT_TASK] Task started for client_id=%s", client_id)
            # 【診断用】強制的に可視化
            effective_call_id = manager._get_effective_call_id()
            self.logger.warning(
                "[DEBUG_PRINT] _queue_initial_audio_sequence called client_id=%s call_id=%s",
                client_id,
                effective_call_id,
            )

            # 【追加】二重実行ガード（通話ごとのフラグチェック）
            if effective_call_id and effective_call_id in manager._initial_sequence_played:
                self.logger.warning(
                    "[INIT_SEQ] Skipping initial sequence for %s (already played).",
                    effective_call_id,
                )
                return

            effective_client_id = client_id or manager.default_client_id
            if not effective_client_id:
                self.logger.warning("[INIT_DEBUG] No effective_client_id, returning early")
                return

            # 無音監視基準時刻を初期化（通話開始時）
            effective_call_id = manager._get_effective_call_id()

            # 【追加】effective_call_idが確定した時点で再度チェック
            if effective_call_id and effective_call_id in manager._initial_sequence_played:
                self.logger.warning(
                    "[INIT_SEQ] Skipping initial sequence for %s (already played, checked after call_id resolution).",
                    effective_call_id,
                )
                return

            # ★フラグセットは削除（キュー追加成功後に移動）★

            if effective_call_id:
                current_time = time.monotonic()
                manager._last_tts_end_time[effective_call_id] = current_time
                manager._last_user_input_time[effective_call_id] = current_time
                # アクティブな通話として登録（重複登録を防ぐ）
                if effective_call_id not in manager._active_calls:
                    self.logger.warning(
                        "[CALL_START_TRACE] [LOC_START] Adding %s to _active_calls (_queue_initial_audio_sequence) at %.3f",
                        effective_call_id,
                        time.time(),
                    )
                    manager._active_calls.add(effective_call_id)
                self.logger.debug(
                    "[CALL_START] Initialized silence monitoring timestamps for call_id=%s",
                    effective_call_id,
                )

            # AICore.on_call_start() を呼び出し（クライアント001専用のテンプレート000-002を再生）
            self.logger.warning(
                "[DEBUG_PRINT] checking on_call_start: hasattr=%s",
                hasattr(manager.ai_core, "on_call_start"),
            )
            if hasattr(manager.ai_core, "on_call_start"):
                try:
                    self.logger.warning(
                        "[DEBUG_PRINT] calling on_call_start call_id=%s client_id=%s",
                        effective_call_id,
                        effective_client_id,
                    )
                    manager.ai_core.on_call_start(
                        effective_call_id, client_id=effective_client_id
                    )
                    self.logger.warning("[DEBUG_PRINT] on_call_start returned successfully")
                    self.logger.info(
                        "[CALL_START] on_call_start() called for call_id=%s client_id=%s",
                        effective_call_id,
                        effective_client_id,
                    )
                except Exception as exc:
                    self.logger.warning("[DEBUG_PRINT] on_call_start exception: %s", exc)
                    self.logger.exception(
                        "[CALL_START] Error calling on_call_start(): %s",
                        exc,
                    )
            else:
                self.logger.warning("[DEBUG_PRINT] on_call_start method not found in ai_core")

            # ★ここでログ出力★
            self.logger.warning(
                "[INIT_DEBUG] Calling play_incoming_sequence for client=%s",
                effective_client_id,
            )
            try:
                # 同期関数をスレッドプールで実行（I/Oブロッキングを回避）
                # ★タイムアウト設定（3秒）★
                self.logger.warning(
                    "[INIT_TIMEOUT_START] Starting wait_for with timeout=3.0 for client=%s",
                    effective_client_id,
                )
                loop = asyncio.get_running_loop()
                audio_paths = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, manager.audio_manager.play_incoming_sequence, effective_client_id
                    ),
                    timeout=3.0,
                )
                # 【追加】デバッグログ：audio_pathsの取得結果を詳細に出力
                self.logger.warning(
                    "[INIT_TIMEOUT_SUCCESS] play_incoming_sequence completed within timeout for %s",
                    effective_client_id,
                )
                self.logger.warning(
                    "[INIT_DEBUG] audio_paths result: %s (count=%s)",
                    [str(p) for p in audio_paths],
                    len(audio_paths),
                )
            except asyncio.TimeoutError:
                self.logger.error(
                    "[INIT_ERR] Initial sequence timed out for client=%s (timeout=3.0s)",
                    effective_client_id,
                )
                self.logger.error(
                    "[INIT_TIMEOUT_ERROR] asyncio.TimeoutError caught for client=%s",
                    effective_client_id,
                )
                # タイムアウト時は空リストとして扱う
                audio_paths = []
            except Exception as exc:
                self.logger.error(
                    "[INIT_ERR] Failed to load incoming sequence for client=%s: %s",
                    effective_client_id,
                    exc,
                )
                self.logger.error(
                    "[INIT_EXCEPTION] Exception type: %s for client=%s",
                    type(exc).__name__,
                    effective_client_id,
                )
                self.logger.error(
                    "[INIT_EXCEPTION] Exception details: %s",
                    str(exc),
                    exc_info=True,
                )
                return
            finally:
                self.logger.warning(
                    "[INIT_FINALLY] Finally block reached for client=%s",
                    effective_client_id,
                )

            if audio_paths:
                self.logger.info(
                    "[client=%s] initial greeting files=%s",
                    effective_client_id,
                    [str(p) for p in audio_paths],
                )
            else:
                self.logger.warning(
                    "[client=%s] No audio files found for initial sequence",
                    effective_client_id,
                )

            chunk_size = 160
            queued_chunks = 0
            queue_labels = []

            # 1) 0.5秒の無音を000よりも前に必ず積む（RTP開始時のノイズ防止）
            gateway = getattr(manager, "gateway", None)
            if gateway and hasattr(gateway, "_generate_silence_ulaw"):
                silence_payload = gateway._generate_silence_ulaw(
                    manager.initial_silence_sec
                )
            else:
                silence_payload = self._generate_silence_ulaw(
                    manager.initial_silence_sec
                )
            silence_samples = len(silence_payload)
            silence_chunks_data = []
            for i in range(0, len(silence_payload), chunk_size):
                silence_chunks_data.append(silence_payload[i : i + chunk_size])
            silence_chunks = len(silence_chunks_data)
            if silence_chunks:
                queue_labels.append(f"silence({manager.initial_silence_sec:.1f}s)")
                self.logger.info(
                    "[client=%s] initial silence queued samples=%d chunks=%d duration=%.3fs",
                    effective_client_id,
                    silence_samples,
                    silence_chunks,
                    silence_samples / 8000.0,
                )

            file_entries = []
            for idx, audio_path in enumerate(audio_paths):
                # 【追加】デバッグログ：各ファイルの処理状況を詳細に出力
                self.logger.warning(
                    "[INIT_DEBUG] Processing audio_path[%s]=%s exists=%s",
                    idx,
                    audio_path,
                    audio_path.exists(),
                )
                if not audio_path.exists():
                    self.logger.warning(
                        "[client=%s] audio file missing: %s",
                        effective_client_id,
                        audio_path,
                    )
                    continue
                try:
                    ulaw_payload = self._load_wav_as_ulaw8k(audio_path)
                    self.logger.warning(
                        "[INIT_DEBUG] Loaded audio_path[%s]=%s payload_len=%s",
                        idx,
                        audio_path,
                        len(ulaw_payload),
                    )
                except Exception as exc:
                    self.logger.error(
                        "[client=%s] failed to prepare %s: %s",
                        effective_client_id,
                        audio_path,
                        exc,
                    )
                    continue
                size = None
                try:
                    size = audio_path.stat().st_size
                except OSError:
                    size = None
                try:
                    rel = str(audio_path.relative_to(_PROJECT_ROOT))
                except ValueError:
                    rel = str(audio_path)
                file_entries.append({"path": rel, "size": size})

                queue_labels.append(audio_path.stem)
                # 2) クライアント設定順（例: 000→001→002）に従い各ファイルを順番に積む
                for i in range(0, len(ulaw_payload), chunk_size):
                    manager.tts_queue.append(ulaw_payload[i : i + chunk_size])
                    queued_chunks += 1

            for chunk in reversed(silence_chunks_data):
                manager.tts_queue.appendleft(chunk)
                queued_chunks += 1

            if file_entries:
                self.logger.info(
                    "[client=%s] initial greeting files=%s",
                    effective_client_id,
                    file_entries,
                )

            if queue_labels:
                pretty_order = " -> ".join(queue_labels)
                pretty_paths = " -> ".join(str(p) for p in audio_paths) or "n/a"
                self.logger.info(
                    "[client=%s] initial queue order=%s (paths=%s)",
                    effective_client_id,
                    pretty_order,
                    pretty_paths,
                )

            if queued_chunks:
                # ★キュー追加成功後、ここで初めてフラグを立てる★
                if effective_call_id:
                    manager._initial_sequence_played.add(effective_call_id)
                    self.logger.warning(
                        "[INIT_SEQ] Flag set for %s. Queued %s chunks.",
                        effective_call_id,
                        queued_chunks,
                    )

                manager.is_speaking_tts = True
                manager.initial_sequence_played = True
                manager.initial_sequence_playing = True  # 初回シーケンス再生中フラグを立てる
                manager.initial_sequence_completed = False
                manager.initial_sequence_completed_time = None
                self.logger.info(
                    "[INITIAL_SEQUENCE] ON: client=%s initial_sequence_playing=True (ASR will be disabled during playback)",
                    effective_client_id,
                )
                self.logger.info(
                    "[client=%s] initial greeting enqueued (%d chunks)",
                    effective_client_id,
                    queued_chunks,
                )
            else:
                # キューに追加できなかった場合
                self.logger.warning(
                    "[INIT_SEQ] No chunks queued for %s. Flag NOT set.",
                    effective_call_id,
                )
        except Exception as exc:
            # ★エラーをキャッチしてログ出しし、ここで止める（伝播させない）★
            self.logger.error(
                "[INIT_ERR] Critical error in initial sequence: %s\n%s",
                exc,
                traceback.format_exc(),
            )

    def _load_wav_as_ulaw8k(self, wav_path: Path) -> bytes:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if n_channels > 1:
            frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
        if sample_width != 2:
            frames = audioop.lin2lin(frames, sample_width, 2)
            sample_width = 2
        if framerate != 8000:
            frames, _ = audioop.ratecv(frames, sample_width, 1, framerate, 8000, None)
        return audioop.lin2ulaw(frames, sample_width)

    def _generate_silence_ulaw(self, duration_sec: float) -> bytes:
        samples = max(1, int(8000 * duration_sec))
        pcm16_silence = b"\x00\x00" * samples
        return audioop.lin2ulaw(pcm16_silence, 2)
