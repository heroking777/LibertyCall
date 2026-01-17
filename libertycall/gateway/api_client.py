"""External API/TTS client initialization extracted from AICore."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ModuleNotFoundError:
    genai = None
    GEMINI_AVAILABLE = False


def init_api_clients(core) -> None:
    """Initialize external API clients (Gemini TTS) for the core instance."""
    core.tts_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TTS")
    core.logger.debug("AICore: TTS ThreadPoolExecutor initialized (max_workers=2)")

    core.debug_save_wav = os.getenv("LC_DEBUG_SAVE_WAV", "0") == "1"
    core.call_id = None
    core._wav_saved = False
    core._wav_chunk_counter = 0

    tts_configs = {
        "000": {
            "voice": "ja-JP-Neural2-B",
            "pitch": 0.0,
            "speaking_rate": 1.2,
        },
        "001": {
            "voice": "ja-JP-Neural2-B",
            "pitch": 2.0,
            "speaking_rate": 1.2,
        },
        "002": {
            "voice": "ja-JP-Wavenet-C",
            "pitch": 0.5,
            "speaking_rate": 1.0,
        },
    }

    tts_conf = tts_configs.get(core.client_id, tts_configs["000"])

    core.use_gemini_tts = False
    core.gemini_model = None

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if not GEMINI_AVAILABLE or not genai:
        core.logger.error(
            "[TTS_INIT] Gemini API (google-generativeai) が利用できません。"
            "インストールしてください: pip install google-generativeai"
        )
        return

    try:
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            core.use_gemini_tts = True
            core.logger.info("[TTS_INIT] Gemini API認証成功 (APIキー使用)")
        elif google_creds:
            try:
                genai.configure(api_key=None)
                core.use_gemini_tts = True
                core.logger.info("[TTS_INIT] Gemini API認証成功 (サービスアカウント使用)")
            except Exception as exc:
                core.logger.error("[TTS_INIT] Gemini API認証失敗 (サービスアカウント): %s", exc)
                return
        else:
            core.logger.error(
                "[TTS_INIT] Gemini API認証情報が未設定です。"
                "GEMINI_API_KEYまたはGOOGLE_APPLICATION_CREDENTIALSを設定してください。"
            )
            return
    except Exception as exc:
        core.logger.error("[TTS_INIT] Gemini API初期化エラー: %s", exc)
        return

    core.tts_config = tts_conf
    core.logger.info(
        "[TTS_PROFILE] client=%s voice=%s speed=%s pitch=%s (Gemini API)",
        core.client_id,
        tts_conf["voice"],
        tts_conf["speaking_rate"],
        tts_conf["pitch"],
    )
