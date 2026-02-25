"""IntentClassifierをStreamingLLMHandler互換インターフェースでラップ"""
import logging
from intent_classifier import IntentClassifier

logger = logging.getLogger(__name__)


class IntentWrapper:
    """
    StreamingLLMHandlerと同じ add_fragment / finalize インターフェースを持つ。
    whisper_session.py の変更を最小限にするためのラッパー。
    """

    def __init__(self, client_id: str):
        config_path = f"/opt/libertycall/clients/{client_id}/config/dialogue_config.json"
        # GPU無しの場合はLLMスキップ（タイムアウトで遅いため）
        import shutil
        has_gpu = shutil.which("nvidia-smi") is not None
        self.classifier = IntentClassifier(config_path, use_llm=has_gpu)
        self._fragments = []
        self._last_rid = None
        logger.info("[INTENT_WRAP] initialized client=%s use_llm=%s", client_id, has_gpu)

    def add_fragment(self, text: str):
        """interim結果を蓄積し、ルールマッチを即座に試行"""
        self._fragments.append(text)
        rid, source, score = self.classifier.classify(text)
        if source == "rule" and score >= 0.55:
            self._last_rid = rid
            logger.info("[INTENT_WRAP] interim match: '%s' -> %s [%s] (%.2f)",
                       text, rid, source, score)

    def finalize(self) -> str:
        """最終結果で分類し、応答IDを返す"""
        if self._fragments:
            # 最後のフラグメント（最終認識結果）で判定
            final_text = self._fragments[-1]
            rid, source, score = self.classifier.classify(final_text)
            logger.info("[INTENT_WRAP] finalize: '%s' -> %s [%s] (%.2f)",
                       final_text, rid, source, score)
            self._fragments.clear()
            self._last_rid = None
            return rid

        # フラグメントが無ければinterimで拾ったものを返す
        if self._last_rid:
            rid = self._last_rid
            self._last_rid = None
            self._fragments.clear()
            return rid

        self._fragments.clear()
        return "114"  # デフォルト聞き返し

    def reset(self):
        self._fragments.clear()
        self._last_rid = None
