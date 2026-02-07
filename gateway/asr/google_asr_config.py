"""Google ASR configuration helpers."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

try:  # pragma: no cover - optional dependency
    from google.cloud.speech_v1p1beta1 import SpeechClient  # type: ignore
    from google.cloud.speech_v1p1beta1.types import cloud_speech  # type: ignore

    GOOGLE_SPEECH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SpeechClient = None  # type: ignore
    cloud_speech = None  # type: ignore
    GOOGLE_SPEECH_AVAILABLE = False

DEFAULT_PROJECT_ID = "libertycall-main"
DEFAULT_ENV_CREDENTIALS_PATH = "/opt/libertycall/config/google-credentials.json"
DEFAULT_CREDENTIALS_CANDIDATES = [
    "/opt/libertycall/key/google_tts.json",
    "/opt/libertycall/key/libertycall-main-7e4af202cdff.json",
]


def resolve_project_id(project_id: Optional[str], logger: logging.Logger) -> str:
    resolved = project_id or os.getenv("LC_GOOGLE_PROJECT_ID") or DEFAULT_PROJECT_ID
    if not resolved:
        logger.warning("LC_GOOGLE_PROJECT_ID が未設定です。デフォルトを使用します。")
        resolved = DEFAULT_PROJECT_ID
    return resolved


def ensure_google_credentials(
    credentials_path: Optional[str],
    logger: logging.Logger,
) -> Optional[str]:
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        if os.path.exists(DEFAULT_ENV_CREDENTIALS_PATH):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = DEFAULT_ENV_CREDENTIALS_PATH
            logger.info(
                "Force set GOOGLE_APPLICATION_CREDENTIALS to %s",
                DEFAULT_ENV_CREDENTIALS_PATH,
            )

    cand_paths: List[str] = []
    env_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if env_creds:
        cand_paths.append(env_creds)
    env_lc_creds = os.getenv("LC_GOOGLE_CREDENTIALS_PATH")
    if env_lc_creds and env_lc_creds not in cand_paths:
        cand_paths.append(env_lc_creds)
    if credentials_path:
        cand_paths.append(credentials_path)
    cand_paths.extend(DEFAULT_CREDENTIALS_CANDIDATES)

    selected_path = None
    for path in cand_paths:
        if path and os.path.exists(path):
            selected_path = path
            break

    if selected_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = selected_path
        logger.info("GoogleASR: using credentials file: %s", selected_path)
    else:
        logger.error("GoogleASR: no valid credentials file found.")

    return selected_path


def build_recognition_config(
    language_code: str,
    sample_rate: int,
    phrase_hints: Optional[List[str]],
) -> "cloud_speech.RecognitionConfig":
    # 【設定確認】ログ出力
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[ASR_CONFIG_BUILD] language_code={language_code}, sample_rate={sample_rate}, encoding=LINEAR16")
    
    config = cloud_speech.RecognitionConfig(  # type: ignore[call-arg]
        encoding=cloud_speech.RecognitionConfig.AudioEncoding.LINEAR16,  # type: ignore[attr-defined]
        sample_rate_hertz=sample_rate,
        language_code=language_code,
        use_enhanced=True,
        audio_channel_count=1,
        enable_separate_recognition_per_channel=False,
        enable_automatic_punctuation=True,
        max_alternatives=1,
        speech_contexts=[cloud_speech.SpeechContext(phrases=["はい", "もしもし", "お電話", "ありがとう", "です", "ます", "よろしく"])],
        model="telephony",  # 最も汎用的な設定に戻す
    )
    if phrase_hints:
        config.speech_contexts = [
            cloud_speech.SpeechContext(phrases=phrase_hints)  # type: ignore[attr-defined]
        ]
    return config


def build_streaming_config(
    recognition_config: "cloud_speech.RecognitionConfig",
) -> "cloud_speech.StreamingRecognitionConfig":
    logging.getLogger(__name__).info(
        "[ASR_STREAM_CONFIG] interim_results=True single_utterance=False enable_voice_activity_events=True"
    )
    return cloud_speech.StreamingRecognitionConfig(  # type: ignore[call-arg]
        config=recognition_config,
        interim_results=True,  # 【強制的にTrue】Googleが途中経過を出すように設定
        single_utterance=False,  # 【強制的にFalse】勝手に耳を閉じさせない
        enable_voice_activity_events=True,
    )
