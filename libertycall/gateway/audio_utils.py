import audioop
import numpy as np
from scipy.signal import resample_poly

def ulaw8k_to_pcm16k(ulaw_bytes):
    """
    Asterisk (u-law 8kHz) -> Whisper (PCM 16kHz)
    """
    # 1. u-law -> PCM 16bit (8kHz)
    pcm_8k = audioop.ulaw2lin(ulaw_bytes, 2)
    
    # 2. Resample 8kHz -> 16kHz (resample_poly使用)
    audio_data = np.frombuffer(pcm_8k, dtype=np.int16)
    audio_resampled = resample_poly(audio_data, 2, 1)  # 8kHz → 16kHz
    
    return audio_resampled.astype(np.int16).tobytes()

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