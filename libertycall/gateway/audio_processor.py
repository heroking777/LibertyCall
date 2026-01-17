#!/usr/bin/env python3
"""Audio processing helpers for realtime gateway."""
import asyncio
import audioop
import os
from typing import Optional


class GatewayAudioProcessor:
    def __init__(self, gateway: "RealtimeGateway"):
        self.gateway = gateway
        self.logger = gateway.logger

    def initialize_asr_settings(
        self,
        *,
        asr_handler_available: bool,
        webrtc_available: bool,
        audio_processing_cls: Optional[object] = None,
        ns_level_cls: Optional[object] = None,
    ) -> None:
        gateway = self.gateway
        # ストリーミングモード判定
        gateway.streaming_enabled = os.getenv("LC_ASR_STREAMING_ENABLED", "0") == "1"

        # ChatGPT音声風: ASRチャンクを短縮（デフォルト250ms）
        os.environ.setdefault("LC_ASR_CHUNK_MS", "250")

        # ChatGPT音声風: TTS送信ループの即時flush用イベント
        gateway._tts_sender_wakeup = asyncio.Event()

        # Google Streaming ASRハンドラー（オプション）
        gateway.asr_handler_enabled = asr_handler_available
        if asr_handler_available:
            self.logger.info("[INIT] Google Streaming ASR handler available")
        else:
            self.logger.warning(
                "[INIT] Google Streaming ASR handler not available (asr_handler module not found)"
            )

        # ASR プロバイダに応じたログ出力
        asr_provider = getattr(gateway.ai_core, "asr_provider", "google")
        if asr_provider == "whisper" and gateway.streaming_enabled:
            model_name = os.getenv("LC_ASR_WHISPER_MODEL", "base")
            chunk_ms = os.getenv("LC_ASR_CHUNK_MS", "250")
            silence_ms = os.getenv("LC_ASR_SILENCE_MS", "700")
            self.logger.info(
                "Streaming ASR モードで起動 (model=%s, chunk=%sms, silence=%sms)",
                model_name,
                chunk_ms,
                silence_ms,
            )
        elif asr_provider == "google" and gateway.streaming_enabled:
            self.logger.info("Streaming ASR モードで起動 (provider=google)")
        else:
            self.logger.info("Batch ASR モードで起動")

        # WebRTC Noise Suppressor初期化（利用可能な場合）
        if webrtc_available and audio_processing_cls and ns_level_cls:
            gateway.ns = audio_processing_cls(ns_level=ns_level_cls.HIGH)
            self.logger.debug("WebRTC Noise Suppressor enabled")
        else:
            gateway.ns = None
            self.logger.warning("WebRTC Noise Suppressor not available, skipping NS processing")

    def _is_silent_ulaw(self, data: bytes, threshold: float = 0.005) -> bool:
        """
        μ-lawデータをPCMに変換してエネルギー判定を行い、無音かどうかを判定

        :param data: μ-lawエンコードされた音声データ
        :param threshold: RMS閾値（デフォルト: 0.005）
        :return: 無音の場合True、有音の場合False
        """
        try:
            import numpy as np

            # μ-law → PCM16変換
            pcm = np.frombuffer(audioop.ulaw2lin(data, 2), dtype=np.int16)
            # RMS計算（正規化: -32768～32767 → -1.0～1.0）
            rms = np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2))
            return rms < threshold
        except Exception as e:
            # エラー時は有音と判定（安全側に倒す）
            self.logger.debug("[RTP_SILENT] Error in _is_silent_ulaw: %s", e)
            return False

    def _apply_agc(self, pcm_data: bytes, target_rms: int = 1000) -> bytes:
        """
        Automatic Gain Control: PCM16 データの音量を自動調整して返す
        :param pcm_data: PCM16 リトルエンディアンのバイト列
        :param target_rms: 目標 RMS 値（デフォルト 1000）
        :return: 増幅後の PCM16 バイト列
        """
        try:
            if not pcm_data or len(pcm_data) == 0:
                return pcm_data

            current_rms = audioop.rms(pcm_data, 2)
            # ほぼ無音は処理しない
            if current_rms < 10:
                return pcm_data

            gain = float(target_rms) / float(current_rms) if current_rms > 0 else 1.0
            # 過増幅を防ぐ（最大10倍、最小0.5倍）
            gain = min(max(gain, 0.5), 10.0)

            amplified = audioop.mul(pcm_data, 2, gain)

            # ログ（最初の数回のみ出力）
            if not hasattr(self, "_agc_log_count"):
                self._agc_log_count = 0
            if self._agc_log_count < 5 or abs(gain - 1.0) > 2.0:
                self.logger.info(
                    "[AGC] current_rms=%s gain=%.2f target_rms=%s",
                    current_rms,
                    gain,
                    target_rms,
                )
                self._agc_log_count += 1

            return amplified
        except Exception as e:
            self.logger.exception("[AGC_ERROR] %s", e)
            return pcm_data
