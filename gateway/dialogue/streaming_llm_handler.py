#!/usr/bin/env python3
"""ストリーミングLLMハンドラ - 断片逐次投入で候補を絞り込む"""
import json
import logging
import time
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

class StreamingLLMHandler:
    def __init__(self, client_id="000"):
        self.client_id = client_id
        self.fragments = []
        self.current_candidates = []
        self.best_response_id = None
        self._lock = threading.Lock()
        self._choices_text = self._build_choices(client_id)

    def _build_choices(self, client_id):
        config_path = f"/opt/libertycall/clients/{client_id}/config/dialogue_config.json"
        try:
            with open(config_path) as f:
                config = json.load(f)
        except Exception:
            return ""
        choices = []
        for pattern in config.get("patterns", []):
            rid = pattern.get("response", "")
            kws = pattern.get("keywords", [])
            desc = "、".join(kws[:3])
            choices.append(f"{rid}: {desc}")
        return "\n".join(choices)

    def add_fragment(self, fragment_text):
        """Whisperからの断片を追加してLLM推論"""
        if not fragment_text or not fragment_text.strip():
            return
        with self._lock:
            self.fragments.append(fragment_text.strip())
            logger.info("[STREAM_LLM] fragment added: %r, total: %d", 
                       fragment_text.strip(), len(self.fragments))
        # デバッグのため同期実行
        self._update_candidates()

    def _update_candidates(self):
        """現在の断片リストからLLM推論して候補を更新"""
        with self._lock:
            fragments_copy = list(self.fragments)
        
        if not fragments_copy:
            return

        from gateway.dialogue.llm_handler import LLMDialogueHandler
        handler = LLMDialogueHandler.get_instance()
        if not handler._ensure_loaded():
            return

        fragments_str = ", ".join([f'"{f}"' for f in fragments_copy])
        prompt = f"""あなたはIVR電話応答システムです。
以下はユーザーの発話を音声認識した断片リストです。不正確・不完全な場合があります。
断片から発話の意図を推測し、最も適切な応答IDを1つだけ返してください。
IDのみを返し、他の文字は出力しないでください。
まだ判断できない場合は PENDING と返してください。
該当なしの場合は DEFAULT と返してください。

選択肢:
{self._choices_text}

音声断片: [{fragments_str}]
応答ID: """

        try:
            start = time.time()
            result = LLMDialogueHandler._llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.1
            )
            answer = result["choices"][0]["message"]["content"].strip()
            elapsed = time.time() - start
            logger.info("[STREAM_LLM] inference: fragments=%r -> %r (%.1fs)", 
                       fragments_copy, answer, elapsed)
            
            with self._lock:
                if answer not in ("PENDING", "DEFAULT", ""):
                    self.best_response_id = answer
                    logger.info("[STREAM_LLM] candidate updated: %s", answer)
        except Exception as e:
            logger.error("[STREAM_LLM] inference error: %s", e)
            import traceback
            logger.error("[STREAM_LLM] traceback: %s", traceback.format_exc())

    def finalize(self):
        """無音検知で確定。現時点の最良候補を返す"""
        with self._lock:
            result = self.best_response_id
            fragments = list(self.fragments)
            logger.info("[STREAM_LLM] finalize: fragments=%r -> response=%s", 
                       fragments, result)
            # リセット
            self.fragments = []
            self.best_response_id = None
            self.current_candidates = []
        return result

    def reset(self):
        """新しい発話のためにリセット"""
        with self._lock:
            self.fragments = []
            self.best_response_id = None
            self.current_candidates = []
