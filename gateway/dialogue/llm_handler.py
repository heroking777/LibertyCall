#!/usr/bin/env python3
"""LLMベースの応答選択ハンドラ"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

class LLMDialogueHandler:
    _instance = None
    _llm = None
    _loaded = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._model_path = "/opt/libertycall/models/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
        self._response_map = {}

    @classmethod
    def _ensure_loaded(cls):
        if cls._loaded:
            return True
        try:
            from llama_cpp import Llama
            logger.info("[LLM] Loading model...")
            start = time.time()
            LLMDialogueHandler._llm = Llama(
                model_path=cls._instance._model_path,
                n_ctx=2048,
                n_threads=4,
                verbose=False
            )
            LLMDialogueHandler._loaded = True
            logger.info("[LLM] Model loaded in %.1fs", time.time() - start)
            return True
        except Exception as e:
            logger.error("[LLM] Failed to load model: %s", e)
            return False

    def _build_prompt(self, text, client_id):
        config_path = f"/opt/libertycall/clients/{client_id}/config/dialogue_config.json"
        try:
            with open(config_path) as f:
                config = json.load(f)
        except Exception:
            return None

        choices = []
        for pattern in config.get("patterns", []):
            rid = pattern.get("response", "")
            kws = pattern.get("keywords", [])
            desc = "、".join(kws[:3])
            choices.append(f"{rid}: {desc}")

        choices_text = "\n".join(choices)
        return f"""あなたはIVR電話応答システムです。
ユーザーの発話に対して、以下の選択肢から最も適切な応答IDを1つだけ返してください。
IDのみを返し、他の文字は出力しないでください。
該当なしの場合は DEFAULT と返してください。

選択肢:
{choices_text}

ユーザー: 「{text}」
応答ID: """

    def get_response(self, text, client_id="000"):
        if not self._ensure_loaded():
            return None

        prompt = self._build_prompt(text, client_id)
        if not prompt:
            return None

        try:
            start = time.time()
            result = LLMDialogueHandler._llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.1
            )
            answer = result["choices"][0]["message"]["content"].strip()
            elapsed = time.time() - start
            logger.info("[LLM] input=%r -> output=%r (%.1fs)", text, answer, elapsed)

            if answer == "DEFAULT" or not answer:
                return None
            return answer
        except Exception as e:
            logger.error("[LLM] Inference error: %s", e)
            return None
