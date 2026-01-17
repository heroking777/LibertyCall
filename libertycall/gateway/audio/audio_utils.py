import audioop
import logging
import numpy as np
from scipy.signal import resample_poly

logger = logging.getLogger("libertycall.gateway.audio.audio_utils")

def ulaw8k_to_pcm16k(ulaw_bytes):
    """
    Asterisk (u-law 8kHz) -> Whisper (PCM 16kHz)
    """
    # 1. u-law -> PCM 16bit (8kHz)
    pcm_8k = audioop.ulaw2lin(ulaw_bytes, 2)
    
    # 追加デバッグ: 変換直後の振幅を標準ライブラリで取得（numpyに依存せず診断可能）
    try:
        max8 = audioop.max(pcm_8k, 2) if pcm_8k else 0
        rms8 = audioop.rms(pcm_8k, 2) if pcm_8k else 0
    except Exception:
        max8 = 0
        rms8 = 0

    # 2. Resample 8kHz -> 16kHz (resample_poly使用)
    audio_data = np.frombuffer(pcm_8k, dtype=np.int16)
    audio_resampled = resample_poly(audio_data, 2, 1)  # 8kHz → 16kHz
    pcm16k_bytes = audio_resampled.astype(np.int16).tobytes()

    # 追加デバッグ: リサンプリング後の振幅も取得してログ出力
    try:
        max16 = audioop.max(pcm16k_bytes, 2) if pcm16k_bytes else 0
        rms16 = audioop.rms(pcm16k_bytes, 2) if pcm16k_bytes else 0
    except Exception:
        max16 = 0
        rms16 = 0

    try:
        logger.debug(
            "[AUDIO_DEBUG] Input bytes=%d PCM8k bytes=%d PCM16k bytes=%d Max8=%d RMS8=%d Max16=%d RMS16=%d",
            len(ulaw_bytes),
            len(pcm_8k),
            len(pcm16k_bytes),
            max8,
            rms8,
            max16,
            rms16,
        )
    except Exception:
        # ログに失敗しても処理は中断しない
        pass

    return pcm16k_bytes

def pcm24k_to_ulaw8k(pcm_bytes_24k):
    """
    Google TTS (PCM 24kHz) -> Asterisk (u-law 8kHz)
    """
    # 1. bytes -> numpy
    audio_data = np.frombuffer(pcm_bytes_24k, dtype=np.int16)
    
    # 2. Resample 24kHz -> 8kHz (1/3にダウンサンプリング、resample_poly使用)
    audio_resampled = resample_poly(audio_data, 1, 3)  # 24kHz → 8kHz
    
    # 3. PCM 16bit -> u-law
    audio_16bit_8k = audio_resampled.astype(np.int16).tobytes()
    ulaw_data = audioop.lin2ulaw(audio_16bit_8k, 2)
    
    return ulaw_data