"""意図分類統合モジュール - RuleRouter + LLMフォールバック"""
import logging
import subprocess
import json
import time

from rule_router import RuleRouter

logger = logging.getLogger(__name__)

DEFAULT_RESPONSE = "114"  # 聞き返し
LLM_TIMEOUT = 10


class IntentClassifier:
    def __init__(self, config_path: str, use_llm: bool = True):
        self.router = RuleRouter(config_path)
        self.use_llm = use_llm
        self.config_path = config_path
        self._choices_text = self._build_choices()
        logger.info("[INTENT] initialized use_llm=%s", use_llm)

    def _build_choices(self) -> str:
        with open(self.config_path, encoding="utf-8") as f:
            config = json.load(f)
        lines = []
        for p in config.get("patterns", []):
            r = p.get("response", "")
            if isinstance(r, list):
                r = r[0]
            kws = p.get("keywords", [])[:5]
            lines.append(f"{r}: {', '.join(kws)}")
        return "\n".join(lines)

    def classify(self, text: str) -> tuple:
        """
        Returns: (response_id: str, source: str, confidence: float)
        source: 'rule', 'llm', 'default'
        """
        if not text or len(text.strip()) == 0:
            return DEFAULT_RESPONSE, "default", 0.0

        # Step 1: RuleRouter
        rid, score = self.router.match(text)
        if rid is not None:
            return rid, "rule", score

        # Step 2: LLM fallback
        if self.use_llm:
            try:
                llm_rid = self._llm_classify(text)
                if llm_rid and llm_rid != "DEFAULT":
                    logger.info("[INTENT] LLM classified: '%s' -> %s", text, llm_rid)
                    return llm_rid, "llm", 0.4
            except Exception as e:
                logger.warning("[INTENT] LLM error: %s", e)

        # Step 3: Default (聞き返し)
        logger.info("[INTENT] default: '%s' -> %s", text, DEFAULT_RESPONSE)
        return DEFAULT_RESPONSE, "default", 0.0

    def _llm_classify(self, text: str) -> str:
        prompt = f"""あなたは電話IVRの意図分類器です。
入力は音声認識テキストです。誤変換・ひらがな・カタカナ・表記ゆれがあります。
発音が近い語を選択肢のキーワードと照合し、最も適切な応答IDを1つだけ返してください。
IDのみ出力。余計な説明不要。該当なしはDEFAULT。

選択肢:
{self._choices_text}

入力: 「{text}」
ID: """
        result = subprocess.run(
            ["ollama", "run", "qwen2:7b", prompt],
            capture_output=True, text=True, timeout=LLM_TIMEOUT
        )
        return result.stdout.strip().split("\n")[0].strip()


if __name__ == "__main__":
    classifier = IntentClassifier(
        "/opt/libertycall/clients/000/config/dialogue_config.json",
        use_llm=True
    )
    tests = [
        "もしもし", "料金はいくらですか", "りょうきんについて",
        "たんとうしゃにかわって", "応募についてです",
        "土器に釣りをしてください", "天気はどうですか",
        "まだまだ人力じゃない", "全然関係ない話",
    ]
    for text in tests:
        rid, source, score = classifier.classify(text)
        print(f"  '{text}' -> {rid} [{source}] (score={score:.2f})")
