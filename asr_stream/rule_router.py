"""ルールベース意図分類エンジン v3 - 最長マッチ優先"""
import json
import logging
import unicodedata

try:
    import jaconv
except ImportError:
    jaconv = None

logger = logging.getLogger(__name__)

YOMI_DICT = {
    "料金":"りょうきん","費用":"ひよう","値段":"ねだん","価格":"かかく","コスト":"こすと",
    "ホームページ":"ほーむぺーじ","サイト":"さいと","ウェブ":"うぇぶ","ネット":"ねっと",
    "拝見":"はいけん","見た":"みた","見ました":"みました",
    "導入":"どうにゅう","始めたい":"はじめたい","申し込み":"もうしこみ",
    "使いたい":"つかいたい","検討":"けんとう",
    "担当者":"たんとうしゃ","人と話":"ひととはな","契約":"けいやく",
    "相談したい":"そうだんしたい","詳しく":"くわしく",
    "早く":"はやく","人間":"にんげん","人に代わ":"ひとにかわ","代われ":"かわれ","変われ":"かわれ",
    "大丈夫":"だいじょうぶ","結構":"けっこう","切ります":"きります",
    "ロボット":"ろぼっと","自動":"じどう","機械":"きかい",
    "岩本":"いわもと","イワモト":"いわもと",
    "ご案内":"ごあんない","ご提案":"ごていあん","法人様向け":"ほうじんさまむけ",
    "資料をお送り":"しりょうをおおくり","広告":"こうこく","求人":"きゅうじん",
    "営業のお電話":"えいぎょうのおでんわ","営業です":"えいぎょうです","営業の電話":"えいぎょうのでんわ",
    "提案":"ていあん","案内":"あんない",
    "システム":"しすてむ","仕組み":"しくみ","技術":"ぎじゅつ",
    "動作":"どうさ","流れ":"ながれ",
    "精度":"せいど","聞き取れる":"ききとれる","認識":"にんしき","正確":"せいかく",
    "セキュリティ":"せきゅりてぃ","個人情報":"こじんじょうほう","安全":"あんぜん",
    "プライバシー":"ぷらいばしー","録音":"ろくおん",
    "カスタマイズ":"かすたまいず","変更":"へんこう","カスタム":"かすたむ","調整":"ちょうせい","設定":"せってい",
    "24時間":"にじゅうよじかん","夜間":"やかん","休日":"きゅうじつ","深夜":"しんや","土日":"どにち",
    "了解":"りょうかい","承知":"しょうち","理解しました":"りかいしました",
    "用件":"ようけん","問い合わせ":"といあわせ","要件":"ようけん",
    "内容":"ないよう","聞きたい":"ききたい","教えてください":"おしえてください",
    "応募":"おうぼ","予約":"よやく","営業時間":"えいぎょうじかん",
    "何時まで":"なんじまで","何時から":"なんじから",
    "開店":"かいてん","閉店":"へいてん","受付時間":"うけつけじかん",
    "キャンセル":"きゃんせる","日程":"にってい",
}


class RuleRouter:
    def __init__(self, config_path: str):
        self.rules = []
        self._load_config(config_path)
        logger.info("[RULE_ROUTER] loaded %d rules (%d keywords)", len(self.rules),
                     sum(len(r["kw_list"]) for r in self.rules))

    def _normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        if jaconv:
            text = jaconv.kata2hira(jaconv.z2h(text, kana=False, digit=True, ascii=True))
        text = text.lower().strip()
        text = text.replace("ー", "").replace("～", "").replace("〜", "").replace("−", "")
        return text

    def _load_config(self, path: str):
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        for p in config.get("patterns", []):
            response = p.get("response", "")
            if isinstance(response, list):
                response = response[0]
            keywords_raw = p.get("keywords", [])
            kw_list = []
            for kw in keywords_raw:
                norm = self._normalize(kw)
                kw_list.append(norm)
                if kw in YOMI_DICT:
                    yomi = self._normalize(YOMI_DICT[kw])
                    if yomi not in kw_list:
                        kw_list.append(yomi)
            self.rules.append({"response": str(response), "kw_list": kw_list})

    def match(self, text: str) -> tuple:
        if not text or len(text.strip()) == 0:
            return None, 0.0

        norm = self._normalize(text)

        # 全マッチを収集し、最長キーワードマッチを優先
        candidates = []
        for rule in self.rules:
            for kw in rule["kw_list"]:
                if not kw:
                    continue
                if norm == kw:
                    candidates.append((rule["response"], len(kw), 1.0))
                elif kw in norm:
                    score = max(len(kw) / max(len(norm), 1), 0.55)
                    candidates.append((rule["response"], len(kw), score))
                elif norm in kw and len(norm) >= 2:
                    candidates.append((rule["response"], len(norm), 0.5))

        if not candidates:
            logger.info("[RULE_ROUTER] no match: '%s' -> LLM fallback", text)
            return None, 0.0

        # 最長キーワードマッチを優先、同じ長さならスコア優先
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        best = candidates[0]

        if best[2] >= 0.5:
            logger.info("[RULE_ROUTER] matched: '%s' -> %s (kw_len=%d, score=%.2f)", text, best[0], best[1], best[2])
            return best[0], best[2]

        return None, 0.0


if __name__ == "__main__":
    import sys
    router = RuleRouter("/opt/libertycall/clients/000/config/dialogue_config.json")
    tests = [
        ("もしもし", "004"), ("こんにちは", "005"),
        ("料金はいくらですか", "122"), ("りょうきんについて", "122"),
        ("もしもーし", "004"), ("ほーむぺーじみました", "0600"),
        ("たんとうしゃにかわって", "081"), ("導入したいんですけど", "060"),
        ("AIなんですか？", "023_AI_IDENTITY"), ("早くしてくれ", "124"),
        ("いわもとさんいますか", "081"), ("しすてむについて", "006_SYS"),
        ("せきゅりてぃは", "063"), ("にじゅうよじかん対応", "121"),
        ("お願いします", "099"), ("ありがとう", "086"),
        ("応募についてです", "0604"), ("営業時間を教えてください", "0604"),
        ("予約をお願いしたい", "0604"), ("要件について聞きたい", "114"),
    ]
    ok=fb=ng=0
    for text, expected in tests:
        rid, score = router.match(text)
        if rid == expected: print(f"  [OK] '{text}' -> {rid} ({score:.2f})"); ok+=1
        elif rid is None: print(f"  [FB] '{text}' -> FB (exp={expected})"); fb+=1
        else: print(f"  [NG] '{text}' -> {rid} (exp={expected} s={score:.2f})"); ng+=1
    print(f"\n=== OK={ok} FB={fb} NG={ng} / {len(tests)} ===")
