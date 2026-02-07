"""ASR audio processing helpers."""
from __future__ import annotations

import asyncio
import logging
import numpy as np
import os
import time
import audioop
from typing import Optional, Tuple, Union
from scipy.signal import resample_poly


class ASRAudioProcessor:
    def __init__(self, manager: "GatewayASRManager") -> None:
        self.manager = manager
        self.logger = manager.logger

    def extract_rtp_payload(self, data: bytes) -> bytes:
        # 【RTPペイロードの完全な生データを100バイトだけ16進数で出力】
        if len(data) >= 12:
            payload_raw = data[12:]
            self.logger.warning(f"[RTP_RAW_PAYLOAD_100BYTES] Raw payload (first 100 bytes): {payload_raw[:100].hex()}")
            
            # 【バイト・アライメント（ズレ）の確認】
            # パケットの先頭に0x80や0x00のような規則的なヘッダーが残っていないか？
            head_bytes = payload_raw[:10]
            head_hex = head_bytes.hex()
            self.logger.warning(f"[RTP_HEADER_CHECK] First 10 bytes: {head_hex}")
            
            # オフセットをずらしたデコードも試す（1-4バイトずらしてテスト）
            best_offset_payload = None
            best_offset_unique = 0
            best_offset_method = "unknown"
            
            for offset in range(0, 5):  # 0-4バイトオフセットを試す
                if len(payload_raw) > offset:
                    offset_payload = payload_raw[offset:]
                    self.logger.info(f"[OFFSET_TEST] Testing offset={offset}, remaining_bytes={len(offset_payload)}")
                    
                    # 各オフセットで3パターンのデコードを試す
                    offset_best_unique = 0
                    offset_best_payload = None
                    offset_best_method = "unknown"
                    
                    # 方法1: μ-lawデコード
                    try:
                        ulaw_decoded = audioop.ulaw2lin(offset_payload, 2)
                        ulaw_samples = np.frombuffer(ulaw_decoded[:1000], dtype=np.int16) if len(ulaw_decoded) >= 1000 else np.frombuffer(ulaw_decoded, dtype=np.int16)
                        ulaw_unique = len(np.unique(ulaw_samples))
                        self.logger.info(f"[OFFSET_{offset}_ULAW] unique values: {ulaw_unique}")
                        
                        if ulaw_unique > offset_best_unique:
                            offset_best_unique = ulaw_unique
                            offset_best_payload = ulaw_decoded
                            offset_best_method = "ulaw"
                    except Exception as e:
                        self.logger.debug(f"[OFFSET_{offset}_ULAW] decode failed: {e}")
                    
                    # 方法2: A-lawデコード
                    try:
                        alaw_decoded = audioop.alaw2lin(offset_payload, 2)
                        alaw_samples = np.frombuffer(alaw_decoded[:1000], dtype=np.int16) if len(alaw_decoded) >= 1000 else np.frombuffer(alaw_decoded, dtype=np.int16)
                        alaw_unique = len(np.unique(alaw_samples))
                        self.logger.info(f"[OFFSET_{offset}_ALAW] unique values: {alaw_unique}")
                        
                        if alaw_unique > offset_best_unique:
                            offset_best_unique = alaw_unique
                            offset_best_payload = alaw_decoded
                            offset_best_method = "alaw"
                    except Exception as e:
                        self.logger.debug(f"[OFFSET_{offset}_ALAW] decode failed: {e}")
                    
                    # 方法3: そのまま（L16）
                    try:
                        l16_samples = np.frombuffer(offset_payload[:1000], dtype=np.int16) if len(offset_payload) >= 1000 else np.frombuffer(offset_payload, dtype=np.int16)
                        l16_unique = len(np.unique(l16_samples))
                        self.logger.info(f"[OFFSET_{offset}_L16] unique values: {l16_unique}")
                        
                        if l16_unique > offset_best_unique:
                            offset_best_unique = l16_unique
                            offset_best_payload = offset_payload
                            offset_best_method = "l16"
                    except Exception as e:
                        self.logger.debug(f"[OFFSET_{offset}_L16] analysis failed: {e}")
                    
                    self.logger.info(f"[OFFSET_{offset}_BEST] method={offset_best_method}, unique={offset_best_unique}")
                    
                    # 全オフセットの中で最も良いものを記録
                    if offset_best_unique > best_offset_unique:
                        best_offset_unique = offset_best_unique
                        best_offset_payload = offset_best_payload
                        best_offset_method = f"offset_{offset}_{offset_best_method}"
            
            self.logger.warning(f"[GLOBAL_BEST] method={best_offset_method}, unique values={best_offset_unique}")
            
            # 【無音（DCオフセット）の除去】
            if best_offset_payload is not None:
                try:
                    samples = np.frombuffer(best_offset_payload, dtype=np.int16)
                    dc_offset = np.mean(samples)
                    self.logger.info(f"[DC_OFFSET] before removal: {dc_offset:.2f}")
                    
                    # DCオフセットを除去（閾値を下げてより積極的に対応）
                    if abs(dc_offset) > 50:  # 閾値を100から50に下げ
                        dc_corrected_samples = samples - dc_offset
                        dc_corrected_samples = np.clip(dc_corrected_samples, -32768, 32767)
                        dc_corrected_payload = dc_corrected_samples.astype(np.int16).tobytes()
                        
                        # 除去後の分析
                        dc_corrected_unique = len(np.unique(dc_corrected_samples[:1000]))
                        self.logger.info(f"[DC_OFFSET] removed, unique values: {dc_corrected_unique}")
                        
                        if dc_corrected_unique > best_offset_unique:
                            best_offset_payload = dc_corrected_payload
                            best_offset_unique = dc_corrected_unique
                            self.logger.info(f"[DC_OFFSET] Using DC corrected payload")
                    else:
                        self.logger.info(f"[DC_OFFSET] minimal, keeping original")
                        
                except Exception as e:
                    self.logger.error(f"[DC_OFFSET] correction failed: {e}")
            
            # 【自動音量調整】RMSを計算して適切なレベルに増幅
            if best_offset_payload is not None:
                try:
                    samples = np.frombuffer(best_offset_payload, dtype=np.int16)
                    rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
                    self.logger.info(f"[VOLUME_CHECK] {best_offset_method} RMS: {rms:.2f}")
                    
                    # 🔥 水増しを全廃。生の声の鮮度だけを追求。
                    # 増幅は一切行わず、RTPから届いた生の声をそのまま使用
                    self.logger.warning(f"[NO_AMPLIFICATION] Using raw voice without amplification - RMS: {rms:.2f}")
                    best_offset_unique = len(np.unique(samples[:1000]))
                    
                    # 🔥 合成ノイズと強制正規化を全廃
                    # 生の声以外は一切使用しない
                    
                    # 【サンプリングレート固定】8kHzのまま生で投げる
                    self.logger.warning(f"[RAW_8KHZ] Sending raw 8kHz voice without resampling - unique: {best_offset_unique}")
                    
                    if best_offset_unique > 100:  # 閾値を下げて生の声を重視
                        self.logger.info(f"[RAW_VOICE] Natural voice detected with {best_offset_unique} unique values")
                        return best_offset_payload
                    else:
                        self.logger.warning(f"[RAW_VOICE] Too few unique values ({best_offset_unique}), but using raw voice anyway")
                        return best_offset_payload
                        
                except Exception as e:
                    self.logger.error(f"[VOLUME_CHECK] {best_offset_method} processing failed: {e}")
                    return best_offset_payload
            
            # 従来のペイロードタイプ判定（フォールバック）
            payload_type = data[1] & 0x7F
            self.logger.info(f"[FALLBACK] RTP payload_type={payload_type}, data_len={len(data)}")
            
            if payload_type == 0:  # PCMU (μ-law)
                self.logger.warning("[FALLBACK] Detected PCMU (μ-law)")
                return audioop.ulaw2lin(payload_raw, 2) if len(payload_raw) > 0 else data[12:]
            elif payload_type == 8:  # PCMA (A-law)
                self.logger.warning("[FALLBACK] Detected PCMA (A-law)")
                return audioop.alaw2lin(payload_raw, 2) if len(payload_raw) > 0 else data[12:]
            elif payload_type == 127:  # 動的ペイロードタイプ
                self.logger.info("[FALLBACK] Dynamic payload type")
                return payload_raw
            else:
                self.logger.warning(f"[FALLBACK] Unknown payload_type={payload_type}")
                return payload_raw
        else:
            self.logger.warning(f"[FALLBACK] Too short data: {len(data)} bytes")
            return data

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

    def _is_silent_l16(self, data: bytes, threshold: float = 0.005) -> bool:
        """
        L16 (Linear PCM 16bit) データのエネルギー判定を行い、無音かどうかを判定

        :param data: L16 PCM16音声データ
        :param threshold: RMS閾値（デフォルト: 0.005）
        :return: 無音の場合True、有音の場合False
        """
        try:
            # L16 PCM16データを直接処理
            pcm = np.frombuffer(data, dtype=np.int16)
            # RMS計算（正規化: -32768～32767 → -1.0～1.0）
            rms = np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2))
            return rms < threshold
        except Exception as exc:
            # エラー時は有音と判定（安全側に倒す）
            self.logger.debug("[RTP_SILENT] Error in _is_silent_l16: %s", exc)
            return False

    def update_vad_state(self, effective_call_id: str, pcm_data: bytes) -> Tuple[float, bool]:
        manager = self.manager
        current_time = time.monotonic()
        # 【適正化】実運用向けのVAD閾値に戻す
        threshold = 0.015
        
        # 【Pre-rollバッファ】音声検知前後の500msを保持
        if not hasattr(manager, '_pre_roll_buffer'):
            manager._pre_roll_buffer = bytearray()
            manager._pre_roll_start_time = current_time
        
        # 常にPre-rollバッファにデータを追加（最大1秒分）
        pre_roll_duration = (current_time - manager._pre_roll_start_time) * 1000
        if pre_roll_duration < 1000:  # 1秒未満なら保持
            manager._pre_roll_buffer.extend(pcm_data)
        else:
            # 1秒超えたら古いデータを削除
            manager._pre_roll_buffer = bytearray()
            manager._pre_roll_buffer.extend(pcm_data)
            manager._pre_roll_start_time = current_time

        # RMS値を計算（有音・無音判定用）
        try:
            # L16 PCM16データを直接処理
            pcm = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 【徹底分析】パケットの中身を確認
            if len(pcm) > 0:
                max_sample = np.max(np.abs(pcm))
                min_sample = np.min(pcm)
                mean_sample = np.mean(pcm)
                # 最初の10サンプルをhexで出力
                first_10_hex = pcm[:10].tobytes().hex()
                
                self.logger.info(f"[PACKET_ANALYSIS] len={len(pcm)} max={max_sample} min={min_sample} mean={mean_sample:.3f}")
                self.logger.info(f"[PACKET_ANALYSIS] first_10_hex={first_10_hex}")
                
                # 【エンディアン確認】0xffffパターンは無音データ
                if first_10_hex.startswith('ffff'):
                    self.logger.info("[BYTE_ORDER] Detected silent audio (ffff) - no byteswap needed")
                else:
                    self.logger.warning(f"[BYTE_ORDER] Unexpected pattern: {first_10_hex}")
                
                # 【ゲイン再強化】10倍に増幅してテスト
                pcm_amplified = np.clip(pcm * 10, -32768, 32767)
                max_amp = np.max(np.abs(pcm_amplified))
                self.logger.info(f"[PACKET_ANALYSIS] after_10x_gain max_amp={max_amp}")
                
                # 【サンプリングレート強制一致】FreeSWITCHは16kHzで送信している
                pcm_data = pcm_amplified.astype(np.int16).tobytes()
                self.logger.info(f"[SAMPLING_RATE] Using 16kHz as confirmed from FreeSWITCH")
                
                # 【ASR設定確認】現在の設定をログ出力
                asr_sample_rate = getattr(self.manager, 'sample_rate', 'UNKNOWN')
                asr_language = getattr(self.manager, 'language_code', 'UNKNOWN')
                self.logger.info(f"[ASR_CONFIG_CHECK] sample_rate={asr_sample_rate}, language_code={asr_language}")
                
                # 元の2倍増幅も比較用に保持
                pcm_original = np.clip(pcm * 2, -32768, 32767)
            else:
                self.logger.warning(f"[PACKET_ANALYSIS] Empty PCM data!")
                pcm_amplified = pcm
                pcm_original = pcm
            
            pcm_data = pcm_amplified.astype(np.int16).tobytes()
            
            # RMS計算（正規化: -32768～32767 → -1.0～1.0）
            rms = np.sqrt(np.mean((pcm_amplified.astype(np.float32) / 32768.0) ** 2))
            
            # 【VADバイパス】強制的に音声ありと判定（テスト用）
            is_voice = True
            # is_voice = rms >= threshold  # 元の判定（コメントアウト）
            
            # 【Pre-roll送信】音声検出時にPre-rollバッファを含めて送信
            if is_voice and hasattr(manager, '_pre_roll_buffer') and len(manager._pre_roll_buffer) > 0:
                # Pre-rollデータを現在のデータの前に追加
                pre_roll_data = bytes(manager._pre_roll_buffer)
                combined_data = pre_roll_data + pcm_data
                self.logger.info(f"[PRE_ROLL_SEND] Added {len(pre_roll_data)} bytes pre-roll to {len(pcm_data)} bytes current")
                
                # Pre-rollバッファをクリア
                manager._pre_roll_buffer.clear()
                manager._pre_roll_start_time = current_time
                
                # 結合データで処理を継続
                pcm = np.frombuffer(combined_data, dtype=np.int16)
                self.logger.info(f"[PRE_ROLL_COMBINED] Total data size: {len(pcm)} samples")
            
            # 【確実な送信パイプライン】is_voice=Trueなら一直線に送信
            if is_voice:
                self.logger.info(f"[DIRECT_SEND] is_voice=True, executing guaranteed send pipeline")
                
                try:
                    from asr_handler import get_or_create_handler
                    from google_stream_asr import GoogleStreamingASR
                    
                    effective_call_id = getattr(manager, 'call_id', None) or getattr(manager, '_effective_call_id', None)
                    if not effective_call_id:
                        self.logger.error(f"[DIRECT_SEND] No effective_call_id available")
                        return rms, True
                    
                    # 確実なハンドラー取得
                    handler = get_or_create_handler(effective_call_id)
                    if not handler:
                        self.logger.error(f"[DIRECT_SEND] Failed to get handler for {effective_call_id}")
                        return rms, True
                    
                    # 確実なASR初期化
                    if not handler.asr:
                        self.logger.info(f"[DIRECT_SEND] Initializing ASR for {effective_call_id}")
                        handler.asr = GoogleStreamingASR()
                        start_result = handler.asr.start_stream()
                        self.logger.info(f"[DIRECT_SEND] ASR streaming started: {start_result}")
                    
                    # 確実なデータ準備（ゲイン10倍 + バイトオーダー反転）
                    final_pcm = np.clip(pcm * 10, -32768, 32767)
                    final_bytes = final_pcm.astype(np.int16).tobytes()
                    swapped_bytes = bytearray(len(final_bytes))
                    for i in range(0, len(final_bytes), 2):
                        if i + 1 < len(final_bytes):
                            swapped_bytes[i] = final_bytes[i + 1]
                            swapped_bytes[i + 1] = final_bytes[i]
                    
                    # ASR入口ログ
                    try:
                        with open("/tmp/gateway_google_asr.trace", "a") as f:
                            f.write(f"[ASR_FEED] len={len(swapped_bytes)} call_id={effective_call_id}\n")
                    except Exception:
                        pass
                    
                    # bytearrayをbytesに変換（Google ASRの型要求）
                    final_swapped_bytes = bytes(swapped_bytes)
                    
                    # 確実な送信実行
                    self.logger.info(f"[DIRECT_SEND] Sending {len(final_swapped_bytes)} bytes to ASR")
                    handler.asr.add_audio(final_swapped_bytes)
                    self.logger.info(f"[DIRECT_SEND] Send completed successfully")
                    
                    # 【ログ監視継続体制】is_voice=Trueでもtranscriptが出ない場合の自動音声保存
                    if hasattr(handler.asr, 'result_text') and handler.asr.result_text:
                        self.logger.info(f"[VOICE_MONITOR] ASR has result: '{handler.asr.result_text}'")
                    else:
                        # transcriptが出ない場合は音声データを自動保存して検証
                        import datetime
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                        save_dir = "/opt/libertycall/audio_recordings/voice_monitor"
                        os.makedirs(save_dir, exist_ok=True)
                        save_path = f"{save_dir}/rtp_voice_{effective_call_id}_{timestamp}.raw"
                        
                        try:
                            with open(save_path, "wb") as f:
                                f.write(final_swapped_bytes)
                            self.logger.warning(f"[VOICE_MONITOR] No transcript detected, saved RTP audio to {save_path}")
                            self.logger.warning(f"[VOICE_MONITOR] Audio data: {len(final_swapped_bytes)} bytes, first_20_hex={final_swapped_bytes[:20].hex()}")
                            
                            # 音声データの内容を分析
                            max_sample = np.max(np.abs(final_pcm))
                            mean_sample = np.mean(np.abs(final_pcm))
                            self.logger.warning(f"[VOICE_MONITOR] Audio analysis: max={max_sample}, mean_abs={mean_sample:.3f}")
                            
                            if max_sample < 100:
                                self.logger.error(f"[VOICE_MONITOR] Audio appears to be silent or very quiet!")
                            else:
                                self.logger.info(f"[VOICE_MONITOR] Audio contains actual voice data")
                                
                        except Exception as save_e:
                            self.logger.error(f"[VOICE_MONITOR] Failed to save audio: {save_e}")
                    
                except Exception as e:
                    self.logger.error(f"[DIRECT_SEND] Pipeline failed: {e}", exc_info=True)
            
            # デバッグ：RMS値と判定結果を記録（毎回出力）
            self.logger.info(f"[VAD_ANALYSIS] RMS={rms:.6f}, threshold={threshold}, is_voice={is_voice}")
            
        except Exception as exc:
            # エラー時は有音と判定（安全側に倒す）
            self.logger.error(f"[RTP_SILENT] Error in RMS calculation: {exc}", exc_info=True)
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

        # L16 PCM16 (8kHz) データを直接処理
        # まずはデコード前/後のバイト列を常時ログ出力して原因を特定する
        try:
            if pcm_data and len(pcm_data) > 0:
                in_hex = (
                    pcm_data[:10].hex() if len(pcm_data) >= 10 else pcm_data.hex()
                )
                self.logger.warning(
                    f"[L16_INPUT] call_id={effective_call_id} len={len(pcm_data)} hex={in_hex}"
                )
        except Exception:
            # ログ失敗は致命的でない
            pass

        # L16データは既にPCM16なので変換不要
        pcm16_8k = pcm_data

        # デコード後の先頭バイトとRMSを必ずログ出力
        try:
            if pcm16_8k and len(pcm16_8k) > 0:
                out_hex = (
                    pcm16_8k[:10].hex() if len(pcm16_8k) >= 10 else pcm16_8k.hex()
                )
                out_rms = audioop.rms(pcm16_8k, 2)
                self.logger.warning(
                    f"[L16_OUTPUT] call_id={effective_call_id} len={len(pcm16_8k)} rms={out_rms} hex={out_hex}"
                )
        except Exception:
            pass

        # AGC はテスト時は無効化済み。8kHz の RMS を再計算して以降の閾値判定に使用
        rms = audioop.rms(pcm16_8k, 2) if pcm16_8k else 0

        # 音声デコード確認ログ（L16データは既にPCM16）
        if manager._debug_packet_count <= 50 or manager._debug_packet_count % 100 == 0:
            # L16 PCM16の先頭10バイト（5サンプル分）
            decoded_preview = (
                pcm16_8k[:10].hex() if len(pcm16_8k) >= 10 else "N/A"
            )
            # 入力データの先頭10バイト（L16なので同じ）
            raw_preview = pcm_data[:10].hex() if len(pcm_data) >= 10 else "N/A"
            self.logger.warning(
                f"[AUDIO_DEBUG] Cnt={manager._debug_packet_count} RawHead={raw_preview} "
                f"L16Head={decoded_preview} RawLen={len(pcm_data)} "
                f"L16Len={len(pcm16_8k)} RMS={rms}"
            )

        # 【診断用】L16 PCM16データのRMS値確認（常に出力、最初の50回のみ詳細）
        if not hasattr(manager, "_rms_debug_count"):
            manager._rms_debug_count = 0
        if manager._rms_debug_count < 50:
            import struct

            # PCM16 (8kHz) データのサンプルを確認
            samples_8k = struct.unpack(f"{len(pcm16_8k)//2}h", pcm16_8k)
            max_sample_8k = max(abs(s) for s in samples_8k) if samples_8k else 0
            self.logger.info(
                f"[RTP_AUDIO_RMS] call_id={effective_call_id} stage=l16_raw len={len(pcm16_8k)} rms={rms} max_amplitude={max_sample_8k} pcm_data_len={len(pcm_data)}"
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
                    f"[RTP_AUDIO_RMS] call_id={effective_call_id} stage=l16_raw rms={rms}"
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
