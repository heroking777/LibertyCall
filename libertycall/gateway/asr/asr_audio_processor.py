"""ASR audio processing helpers."""
from __future__ import annotations

import asyncio
import audioop
import time
from typing import Optional, Tuple

import numpy as np
from scipy.signal import resample_poly


class ASRAudioProcessor:
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def extract_rtp_payload(self, data: bytes) -> bytes:
        return data[12:]

    def log_rtp_payload_debug(self, pcm_data: bytes, effective_call_id: Optional[str]) -> None:
        manager = self.manager
        # 追加診断ログ: RTPペイロードの先頭バイトをヘックスで出力（ASR送信直前の確認用、最初の20パケットのみ）
        try:
            if not hasattr(manager, "_rtp_raw_payload_count"):
                manager._rtp_raw_payload_count = 0
            if manager._rtp_raw_payload_count < 20 and len(pcm_data) > 0:
                try:
                    head_hex = (
                        pcm_data[:10].hex() if len(pcm_data) >= 10 else pcm_data.hex()
                    )
                except Exception:
                    head_hex = "N/A"
                self.logger.warning(
                    f"[RTP_RAW_PAYLOAD] Size={len(pcm_data)} Head={head_hex}"
                )
                manager._rtp_raw_payload_count += 1
        except Exception:
            # ログ出力失敗は処理を中断させない
            pass

        # 【診断用】生のRTPペイロード（デコード前）をダンプ（最初の5パケットのみ）
        if not hasattr(manager, "_payload_raw_debug_count"):
            manager._payload_raw_debug_count = 0
        if manager._payload_raw_debug_count < 5 and len(pcm_data) > 0:
            self.logger.warning(
                f"[PAYLOAD_RAW] Cnt={manager._payload_raw_debug_count} Len={len(pcm_data)} Head={pcm_data[:10].hex()}"
            )
            manager._payload_raw_debug_count += 1

        # 音声デコード確認ログ用カウンター（デコード処理後に出力）
        if not hasattr(manager, "_debug_packet_count"):
            manager._debug_packet_count = 0
        manager._debug_packet_count += 1

        # 【診断用】RTPペイロード抽出直後の確認（最初の数回のみ）
        if not hasattr(manager, "_rtp_payload_debug_count"):
            manager._rtp_payload_debug_count = 0
        if manager._rtp_payload_debug_count < 5 and effective_call_id:
            # μ-lawデータのサンプル値を確認（最初の10バイト）
            sample_bytes = pcm_data[: min(10, len(pcm_data))]
            self.logger.info(
                f"[RTP_PAYLOAD_DEBUG] call_id={effective_call_id} payload_len={len(pcm_data)} first_bytes={sample_bytes.hex()}"
            )
            manager._rtp_payload_debug_count += 1

    def _is_silent_ulaw(self, data: bytes, threshold: float = 0.005) -> bool:
        """
        μ-lawデータをPCMに変換してエネルギー判定を行い、無音かどうかを判定

        :param data: μ-lawエンコードされた音声データ
        :param threshold: RMS閾値（デフォルト: 0.005）
        :return: 無音の場合True、有音の場合False
        """
        try:
            # μ-law → PCM16変換
            pcm = np.frombuffer(audioop.ulaw2lin(data, 2), dtype=np.int16)
            # RMS計算（正規化: -32768～32767 → -1.0～1.0）
            rms = np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2))
            return rms < threshold
        except Exception as exc:
            # エラー時は有音と判定（安全側に倒す）
            self.logger.debug("[RTP_SILENT] Error in _is_silent_ulaw: %s", exc)
            return False

    def update_vad_state(self, effective_call_id: str, pcm_data: bytes) -> Tuple[float, bool]:
        manager = self.manager
        current_time = time.monotonic()
        threshold = 0.005

        # RMS値を計算（有音・無音判定用）
        try:
            # μ-law → PCM16変換
            pcm = np.frombuffer(audioop.ulaw2lin(pcm_data, 2), dtype=np.int16)
            # RMS計算（正規化: -32768～32767 → -1.0～1.0）
            rms = np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2))
            is_voice = rms >= threshold
        except Exception as exc:
            # エラー時は有音と判定（安全側に倒す）
            self.logger.debug(f"[RTP_SILENT] Error in RMS calculation: {exc}")
            rms = threshold
            is_voice = True

        if is_voice:
            # 有音検出時のみ _last_voice_time を更新
            manager._last_voice_time[effective_call_id] = current_time
            # 有音を検出したら無音記録をリセット
            if effective_call_id in manager._last_silence_time:
                del manager._last_silence_time[effective_call_id]
                self.logger.debug(
                    f"[RTP_VOICE] Voice detected (RMS={rms:.4f}) for call_id={effective_call_id}, resetting silence time"
                )
            # 有音フレーム検出時は無音カウンターをリセット
            if hasattr(manager, "_silent_frame_count"):
                manager._silent_frame_count = 0

            # ChatGPT音声風: 有音検出時にバックチャネルフラグをリセット
            if not hasattr(manager, "_backchannel_flags"):
                manager._backchannel_flags = {}
            manager._backchannel_flags[effective_call_id] = False
        else:
            # 無音時は _last_voice_time を更新しない（ただし初回のみ初期化）
            # 初回の無音だけ記録（連続無音なら上書きしない）
            if effective_call_id not in manager._last_silence_time:
                manager._last_silence_time[effective_call_id] = current_time
                self.logger.debug(
                    f"[RTP_SILENT] First silent frame detected (RMS={rms:.4f}) for call_id={effective_call_id} at {current_time:.1f}"
                )
            # RTPストリームが届いたという事実を記録（_last_voice_time が存在しない場合のみ初期化）
            if effective_call_id not in manager._last_voice_time:
                manager._last_voice_time[effective_call_id] = current_time
                self.logger.debug(
                    f"[RTP_INIT] Initialized _last_voice_time for silent stream call_id={effective_call_id}"
                )

            # ChatGPT音声風: 2秒以上無音が続いたらバックチャネルを挿入
            if effective_call_id in manager._last_voice_time:
                silence_duration = current_time - manager._last_voice_time[effective_call_id]
                if silence_duration >= 2.0:
                    # バックチャネルフラグを初期化（存在しない場合）
                    if not hasattr(manager, "_backchannel_flags"):
                        manager._backchannel_flags = {}
                    # まだバックチャネルを送っていない場合のみ送信
                    if not manager._backchannel_flags.get(effective_call_id, False):
                        manager._backchannel_flags[effective_call_id] = True
                        self.logger.debug(
                            f"[BACKCHANNEL_SILENCE] call_id={effective_call_id} silence={silence_duration:.2f}s -> sending backchannel"
                        )
                        # 非同期タスクでバックチャネルを送信
                        try:
                            if (
                                hasattr(manager.ai_core, "tts_callback")
                                and manager.ai_core.tts_callback
                            ):
                                manager.ai_core.tts_callback(
                                    effective_call_id, "はい", None, False
                                )
                                self.logger.info(
                                    f"[BACKCHANNEL_SENT] call_id={effective_call_id} text='はい' (silence={silence_duration:.2f}s)"
                                )
                        except Exception as exc:
                            self.logger.exception(
                                f"[BACKCHANNEL_ERROR] call_id={effective_call_id} error={exc}"
                            )

            # デバッグログは頻度を下げる（100フレームに1回）
            if not hasattr(manager, "_silent_frame_count"):
                manager._silent_frame_count = 0
            manager._silent_frame_count += 1
            if manager._silent_frame_count % 100 == 0:
                self.logger.debug(
                    f"[RTP_SILENT] Detected silent frame (RMS < {threshold}) count={manager._silent_frame_count}"
                )

        return rms, is_voice

    def process_pcm_payload(self, pcm_data: bytes, effective_call_id: str) -> Tuple[bytes, int]:
        manager = self.manager

        # μ-law → PCM16 (8kHz) に変換
        # まずはデコード前/後のバイト列を常時ログ出力して原因を特定する
        try:
            if pcm_data and len(pcm_data) > 0:
                in_hex = (
                    pcm_data[:10].hex() if len(pcm_data) >= 10 else pcm_data.hex()
                )
                self.logger.warning(
                    f"[ULAW_INPUT] call_id={effective_call_id} len={len(pcm_data)} hex={in_hex}"
                )
        except Exception:
            # ログ失敗は致命的でない
            pass

        try:
            pcm16_8k = audioop.ulaw2lin(pcm_data, 2)
        except Exception as exc:
            self.logger.error(
                f"[ULAW_ERROR] call_id={effective_call_id} ulaw2lin failed: {exc}"
            )
            pcm16_8k = b""

        # デコード後の先頭バイトとRMSを必ずログ出力
        try:
            if pcm16_8k and len(pcm16_8k) > 0:
                out_hex = (
                    pcm16_8k[:10].hex() if len(pcm16_8k) >= 10 else pcm16_8k.hex()
                )
                out_rms = audioop.rms(pcm16_8k, 2)
                self.logger.warning(
                    f"[ULAW_OUTPUT] call_id={effective_call_id} len={len(pcm16_8k)} rms={out_rms} hex={out_hex}"
                )
        except Exception:
            pass

        # AGC はテスト時は無効化済み。8kHz の RMS を再計算して以降の閾値判定に使用
        rms = audioop.rms(pcm16_8k, 2) if pcm16_8k else 0

        # 音声デコード確認ログ（デコード後のデータを更新）
        if manager._debug_packet_count <= 50 or manager._debug_packet_count % 100 == 0:
            # デコード後（PCM16）の先頭10バイト（5サンプル分）
            decoded_preview = (
                pcm16_8k[:10].hex() if len(pcm16_8k) >= 10 else "N/A"
            )
            # デコード前（μ-law）の先頭10バイト（既に取得済み）
            raw_preview = pcm_data[:10].hex() if len(pcm_data) >= 10 else "N/A"
            self.logger.warning(
                f"[AUDIO_DEBUG] Cnt={manager._debug_packet_count} RawHead={raw_preview} "
                f"DecodedHead={decoded_preview} RawLen={len(pcm_data)} "
                f"DecodedLen={len(pcm16_8k)} RMS={rms}"
            )

        # 【診断用】μ-lawデコード後のRMS値確認（常に出力、最初の50回のみ詳細）
        if not hasattr(manager, "_rms_debug_count"):
            manager._rms_debug_count = 0
        if manager._rms_debug_count < 50:
            import struct

            # PCM16 (8kHz) データのサンプルを確認
            samples_8k = struct.unpack(f"{len(pcm16_8k)//2}h", pcm16_8k)
            max_sample_8k = max(abs(s) for s in samples_8k) if samples_8k else 0
            self.logger.info(
                f"[RTP_AUDIO_RMS] call_id={effective_call_id} stage=ulaw_decode len={len(pcm16_8k)} rms={rms} max_amplitude={max_sample_8k} pcm_data_len={len(pcm_data)}"
            )
            # 最初の5サンプルをログ出力
            if len(samples_8k) >= 5:
                self.logger.info(
                    f"[RTP_AUDIO_SAMPLES] call_id={effective_call_id} first_5_samples={samples_8k[:5]}"
                )
            manager._rms_debug_count += 1
        else:
            # 50回以降はRMS値のみ（頻度を下げる：10回に1回）
            if manager._rms_debug_count % 10 == 0:
                self.logger.info(
                    f"[RTP_AUDIO_RMS] call_id={effective_call_id} stage=ulaw_decode rms={rms}"
                )
            manager._rms_debug_count += 1

        # --- 音量レベル送信（管理画面用） ---
        manager._maybe_send_audio_level(rms)

        # --- バージイン判定（TTS停止のため常に有効） ---
        # 初回シーケンス再生中はバージインを無効化（000→001→002 が必ず流れるように）
        # Googleストリーミング使用時でも、TTS停止のためのBarge-in判定は有効化
        if not manager.initial_sequence_playing:
            if rms > manager.BARGE_IN_THRESHOLD:
                manager.is_user_speaking = True
                manager.last_voice_time = time.time()

                # 音声が受信された際に無音検知タイマーをリセット
                if effective_call_id:
                    self.logger.debug(
                        f"[on_audio_activity] Resetting no_input_timer for call_id={effective_call_id} (barge-in detected)"
                    )
                    try:
                        # 直接 create_task を使用（async def 内なので）
                        task = asyncio.create_task(
                            manager._start_no_input_timer(effective_call_id)
                        )
                        self.logger.debug(
                            f"[DEBUG_INIT] Scheduled no_input_timer task on barge-in for call_id={effective_call_id}, task={task}"
                        )
                    except Exception as exc:
                        self.logger.exception(
                            f"[NO_INPUT] Failed to schedule no_input_timer on barge-in for call_id={effective_call_id}: {exc}"
                        )

                if manager.is_speaking_tts:
                    self.logger.info(
                        ">> Barge-in: TTS Stopped (RMS=%d, threshold=%d).",
                        rms,
                        manager.BARGE_IN_THRESHOLD,
                    )
                    manager.tts_queue.clear()
                    manager.is_speaking_tts = False
                    # バージイン時もバッファとタイマーをクリア
                    manager.audio_buffer = bytearray()
                    manager.current_segment_start = None

        # WebRTC Noise Suppressor適用（8kHz PCM16 → NS → 8kHz PCM16）
        if manager.ns is not None:
            pcm16_8k_ns = manager.ns.process_stream(pcm16_8k)
        else:
            pcm16_8k_ns = pcm16_8k  # NSが利用できない場合はそのまま使用

        # 録音（8kHz PCM16 をそのまま記録）
        if manager.recording_enabled and manager.recording_file is not None:
            try:
                manager.recording_file.writeframes(pcm16_8k_ns)
            except Exception as exc:
                self.logger.error("録音エラー: %s", exc, exc_info=True)

        # 8kHz → 16kHz リサンプリング（resample_poly使用）
        pcm16_array = np.frombuffer(pcm16_8k_ns, dtype=np.int16)
        pcm16k_array = resample_poly(pcm16_array, 2, 1)  # 8kHz → 16kHz
        pcm16k_chunk = pcm16k_array.astype(np.int16).tobytes()

        # --- PCM16kデータのデバッグ（最初の数回のみ出力） ---
        if not hasattr(manager, "_pcm16k_debug_count"):
            manager._pcm16k_debug_count = 0
        if manager._pcm16k_debug_count < 5:
            import struct

            # PCM16 (16kHz) データのサンプルを確認
            samples_16k = struct.unpack(f"{len(pcm16k_chunk)//2}h", pcm16k_chunk)
            max_sample_16k = max(abs(s) for s in samples_16k) if samples_16k else 0
            self.logger.info(
                f"[RTP_DEBUG] PCM16_16k: {len(samples_16k)} samples, max_amplitude={max_sample_16k}, rms={rms:.1f}, chunk_len={len(pcm16k_chunk)}"
            )
            manager._pcm16k_debug_count += 1

        return pcm16k_chunk, rms
