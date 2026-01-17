from __future__ import annotations

import unicodedata

from libertycall.gateway.common.text_utils import (
    interpret_handoff_reply as _interpret_handoff_reply,
)

TEMPLATE_CONFIG: dict[str, dict] = {
    "003": {"text": "はい。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "004": {"text": "もしもし。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "005": {"text": "恐れ入ります。ご用件をお伺いしてもよろしいでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "006": {"text": "導入のご相談でよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "006_SYS": {"text": "ありがとうございます。システムについてですね。どのような点が気になっていますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "007": {"text": "システムの詳細についてでよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "008": {"text": "料金のご相談でよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "009": {"text": "その他のご相談でよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "010": {"text": "どのような点が気になっておりますでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "011": {"text": "システムのどの部分についてお伺いでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "012": {"text": "料金のどの項目についてお伺いしましょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "013": {"text": "導入までの流れについてご案内いたしましょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "014": {"text": "AIの応答精度についてでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "015": {"text": "録音・個人情報の取り扱いについてでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "016": {"text": "営業電話フィルタについてでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "017": {"text": "カスタマイズの可否についてでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "018": {"text": "導入スピードについてのご質問でしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "019": {"text": "その他のサービス内容でしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "020": {"text": "当社のAI電話は二十四時間三百六十五日対応で、一次受付から要件確認まで自動で行います。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "021": {"text": "誤案内防止のため、ルールベース方式を採用しています。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "022": {"text": "想定外の内容は、全て担当者へ即転送する安全設計です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "023": {"text": "AIが電話応対し、必要に応じて担当者へ引き継ぎます。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "024": {"text": "個人情報は一切保持せず、その場で処理のみ行います。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "025": {"text": "営業電話のフィルタリングにも対応しております。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "026": {"text": "お客様ごとに応答ルールと音声を調整し、精度を継続的に改善いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "027": {"text": "初期費用は不要で、月額二十万円と通話料のみで運用可能です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "028": {"text": "解約はいつでも可能で、最低利用期間はございません。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "029": {"text": "導入後一週間以内で動作不良などあれば全額返金が可能です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "040": {"text": "料金は月額二十万円となります。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "041": {"text": "通話料は一分あたり約三円から四円ほどです。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "042": {"text": "初期費用は一切かかりません。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "043": {"text": "導入時に当月の日割りと翌月分を合わせて請求いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "044": {"text": "一週間以内は全額返金保証がございます。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "045": {"text": "最低契約期間はございません。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "046": {"text": "月途中でもすぐにご解約いただけます。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "047": {"text": "追加費用なしで24時間稼働いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "048": {"text": "社員教育やトレーニングコストは不要です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "049": {"text": "無人化によるコスト削減が可能です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "060": {"text": "最短即日から導入が可能です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "061": {"text": "必要なのは転送先番号のご指定のみです。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "062": {"text": "全てクラウドで動作し、機材の設置は不要です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "063": {"text": "録音データは安全に管理されます。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "064": {"text": "AIは回答を外部へ送信せず、誤案内を防ぐ構造です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "065": {"text": "リアルタイムで発話割り込みに対応いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "066": {"text": "方言やイントネーションにも柔軟に対応いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "067": {"text": "ルールベース方式のため誤案内リスクが極端に低い設計です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "068": {"text": "毎日ログを分析し、翌日には応答精度を改善します。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "069": {"text": "複数拠点・複数番号の管理にも対応しております。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "080": {"text": "必要に応じて担当者へおつなぎいたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "081": {"text": "それでは担当者におつなぎいたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "082": {"text": "しばらくお待ちください。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "083": {"text": "担当者が不在の場合は折り返しのご案内となります。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "084": {"text": "ご質問は以上でよろしいでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "085": {"text": "他に気になる点はございますでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "086": {"text": "本日のご連絡ありがとうございました。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "087": {"text": "また何かございましたらいつでもお問い合わせください。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "088": {"text": "失礼いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "089": {"text": "ご利用ありがとうございました。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "090": {"text": "現在込み合っております。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "091": {"text": "折り返しご希望でしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "092": {"text": "ただいま確認いたします。少しお待ちください。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "093": {"text": "営業目的のお電話でしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "094": {"text": "恐れ入りますが、営業目的のご連絡はお受けしておりません。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "095": {"text": "担当部署に確認いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "096": {"text": "特定サービスに関するお問い合わせでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "097": {"text": "本日の対応可能な時間帯をご案内いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "098": {"text": "順番にご案内しておりますのでお待ちください。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "099": {"text": "他にお手伝いできることはございますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "100": {"text": "初めてのご相談でよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "101": {"text": "料金についてのお問い合わせでよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "102": {"text": "キャンセルのご相談でよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "103": {"text": "お問い合わせでよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "104": {"text": "担当者におつなぎしてよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "110": {"text": "恐れ入ります、もう一度お聞かせいただけますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "111": {"text": "すみません、聞き取りづらかったためもう一度お願いできますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "112": {"text": "少しゆっくりお話しいただけますでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "113": {"text": "雑音が入ってしまったため、改めてお願いできますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "114": {"text": "ご要件をもう一度お伺いしてもよろしいでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "115": {"text": "どの内容についてのお問い合わせでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "116": {"text": "はい、どういった件かもう少し詳しくお聞かせいただけますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "117": {"text": "今のお言葉、確認のため繰り返していただけますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "118": {"text": "すみません、電話が遠いようです。もう一度お願いします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "119": {"text": "恐れ入りますが、何についてのお電話か改めてお伺いしてもよろしいでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0280": {"text": "私たちのAI電話は、飲食、美容院、クリニックなど幅広く対応しています。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0281": {"text": "個人店や小規模店舗でも導入されています。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0282": {"text": "主要な予約アプリとは連動可能です。内容に応じて追加費用を頂いております。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0283": {"text": "飲食、美容、医療など多くの店舗で導入実績がございます。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0284": {"text": "導入後もチャット・電話でのサポートが可能です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0285": {"text": "不具合があれば即日対応し、自動復旧機能も備えています。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "070": {"text": "予約の取得や変更、キャンセルにも柔軟に対応可能です。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "071": {"text": "ダブルブッキングを避けるように自動で枠を管理します。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "072": {"text": "席数やスタッフごとの予約枠も設定いただけます。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0600": {"text": "AI電話の件ですね。どのあたりが気になっておりますでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0601": {"text": "承知いたしました。折り返し希望として承ります。お名前とご連絡先をお伺いしてもよろしいでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0602": {"text": "恐れ入ります、少し聞き取りづらかったようです。もう一度お願いできますでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0603": {"text": "初期設定はこちらで代行いたしますので、お店側の作業はほとんどございません。スマホだけでもご利用いただけますのでご安心ください。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "0604": {"text": "私では詳細のご案内が難しい内容のため、担当者におつなぎしてもよろしいでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
}

GREETING_KEYWORDS = ["もしもし", "こんにちは", "こんばんは", "おはよう", "はじめまして"]
INQUIRY_KEYWORDS = ["ホームページ", "hp", "lp", "メール", "dm", "導入", "しすてむ", "システム", "サービス", "詳しく", "案内", "相談"]
PRICE_KEYWORDS = ["金額", "料金", "値段", "月額", "費用", "初期費用", "最低契約", "解約", "返金", "無料", "トライアル", "効果", "コスト", "削減", "人件費", "ストレス"]
SETUP_KEYWORDS = [
    "導入したら",
    "いつから",
    "どれくらい",
    "どうやって",
    "設定",
    "初期設定",
    "セットアップ",
    "パソコン",
    "pc",
    "スマホ",
    "電話番号",
    "転送",
    "環境",
    "すぐ使える",
]
FUNCTION_KEYWORDS = [
    "aiの声", "声変え", "テンプレ", "語尾", "聞き取れ", "間違ったら", "クレーム",
    "転送", "予約管理", "予約の変更", "キャンセル", "飲食", "美容院", "施術", "席",
    "スタッフ", "個人情報", "セキュリティ", "録音", "ダブルブッキング", "方言", "精度", "カスタマイズ"
]
SUPPORT_KEYWORDS = ["サポート", "不具合", "エラー", "トラブル", "障害", "バグ"]
END_CALL_KEYWORDS = [
    "もうだいじょうぶ",
    "大丈夫です",
    "他はない",
    "以上です",
    "けっこうです",
    "結構です",
    "そんなもん",
    "大丈夫",
    "もういい",
    "今日は聞くだけ",
    "今日は聞くだけなんで",
    "また考えます",
    "やめときます",
    "やめておきます",
    "また今度",
    "一旦やめて",
]

# YES/NO判定用キーワード（HANDOFF確認用）
YES_KEYWORDS = [
    "はい",
    "ええ",
    "お願いします",
    "お願い",
    "承知",
    "はいお願いします",
]

NO_KEYWORDS = [
    "必要ない",
    "いりません",
    "間に合ってます",
]


def normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.lower()
    normalized = normalized.replace(" ", "").replace("　", "")
    return normalized


def interpret_handoff_reply(
    raw_text: str,
    base_intent: str = "UNKNOWN",
    retry_count: int = 0,
) -> str:
    """Legacy wrapper for tests; align handoff confirmation intent handling."""
    normalized = normalize_text(raw_text)
    if base_intent in ("HANDOFF_CONFIRM_WAIT", "HANDOFF_REQUEST"):
        if any(k in normalized for k in YES_KEYWORDS):
            return "HANDOFF_YES"
        if any(k in normalized for k in NO_KEYWORDS):
            return "HANDOFF_NO"
    return _interpret_handoff_reply(raw_text, retry_count=retry_count)


def classify_intent(text: str) -> str:
    t = normalize_text(text)
    if not t:
        return "UNKNOWN"

    # ノイズ・聞き取れないケースの判定（最優先）
    # ※ 正常な短い返答（「はい」「ええ」など）を弾かないように、
    #    文字数だけでは判定せず、ノイズ語/記号に絞る
    if any(k in t for k in ["ゴニョゴニョ", "ごにょごにょ", "ごにょ", "ゴニョ"]):
        return "NOT_HEARD"
    # 多数の特殊文字（…、。など）を含む場合
    special_chars = ["…", "。", "、", ".", ",", "…"]
    special_count = sum(t.count(c) for c in special_chars)
    if special_count >= 3:
        return "NOT_HEARD"

    # ===== ハンドオフリクエスト判定（YES/NO判定より優先） =====
    # 「担当者お願いします」のような明確なハンドオフリクエストを検出
    handoff_keywords = ["担当者", "たんとうしゃ", "担当の者", "当者", "人間", "オペレーター", "ひと", "人"]
    handoff_verbs = ["つないで", "つなげて", "繋いで", "繋げて", "代わって", "替わって", "変わって", "回して", "まわして"]
    handoff_phrases = ["お願いします", "お願い", "ください", "もらえますか", "してほしい"]
    
    # パターン1: 「担当者」+「お願い」などの組み合わせ
    if any(kw in t for kw in handoff_keywords) and any(phrase in t for phrase in handoff_phrases):
        return "HANDOFF_REQUEST"
    
    # パターン2: 「担当者」+「つないで」などの動詞
    if any(kw in t for kw in handoff_keywords) and any(verb in t for verb in handoff_verbs):
        return "HANDOFF_REQUEST"
    
    # パターン3: 「担当者」単独でも「お願い」が含まれていればハンドオフリクエスト
    if "担当者" in t and ("お願い" in t or "おねがい" in t):
        return "HANDOFF_REQUEST"

    # 代表的な「担当者と話したい」系
    if "担当者" in t and "話" in t:
        return "HANDOFF_REQUEST"

    if ("人間" in t or "オペレーター" in t) and ("話" in t or "繋" in t or "代" in t):
        return "HANDOFF_REQUEST"

    if "人間" in t and "話" in t:
        return "HANDOFF_REQUEST"
    
    # ===== システムについての問い合わせ判定（ハンドオフより優先） =====
    # 「システムについて」という明確な問い合わせを検出（ハンドオフ判定より先に実行）
    if any(kw in t for kw in ["システムについて", "システムの", "システムを", "システムが", "システムに", "システムは", "システムで"]):
        return "SYSTEM_INQUIRY"

    # 営業電話の判定（YES/NOより優先）
    if any(k in t for k in ["営業", "ご提案", "サービスのご提案", "新しいサービス"]):
        return "SALES_CALL"

    # HANDOFF確認のYES/NO
    if any(k in t for k in YES_KEYWORDS):
        return "HANDOFF_YES"
    if any(k in t for k in NO_KEYWORDS):
        return "HANDOFF_NO"
    
    # AI電話の件の判定
    if any(k in t for k in ["ai電話", "aiの電話", "aiの件", "ai電話の件"]):
        return "AI_CALL_TOPIC"

    if any(k in t for k in ["あなたはai", "aiですか", "自己紹介", "あなたは誰", "aiがやってる"]):
        return "AI_IDENTITY"
    
    # 設定難易度の判定（より広範囲の表現に対応）
    setup_difficulty_keywords = [
        "設定むずい", "設定難しい", "設定むずかしい", "設定がむずい", "設定が難しい",
        "設定は難しい", "設定はむずい", "設定はむずかしい",
        "設定するの", "設定するのは", "設定するのが",
        "難しい", "むずい", "むずかしい", "難しそう", "むずかしそう",
        "設定", "セットアップ", "導入", "初期設定"
    ]
    difficulty_terms = ["難", "むず"]
    # 「難しい」系の語がある場合のみ SETUP_DIFFICULTY 判定を行う
    if any(term in t for term in difficulty_terms) and any(
        k in t for k in setup_difficulty_keywords
    ):
        if any(ctx in t for ctx in ["システム", "この", "その", "導入", "初期", "設定"]):
            return "SETUP_DIFFICULTY"
    
    # システム説明の判定
    if any(k in t for k in ["どういうシステム", "どんなシステム", "どういうサービス", "どんなサービス", "これどういう", "どういう"]):
        return "SYSTEM_EXPLAIN"
    
    # 混雑・折り返しの判定
    if any(k in t for k in ["混んでます", "混んでる", "込み合って", "混雑", "混ん"]):
        return "BUSY"
    if any(k in t for k in ["折り返し", "折り返して", "かけ直し", "かけなおし", "折り返しもらえ"]):
        return "CALLBACK_REQUEST"
    
    # 方言・割り込みの判定
    if any(k in t for k in ["関西弁", "方言", "イントネーション"]):
        return "DIALECT"
    if any(k in t for k in ["口挟ん", "割り込ん", "途中で話しても", "途中で口挟ん", "口挟んだり"]):
        return "INTERRUPT"
    
    # 予約機能の判定
    if any(k in t for k in ["予約", "キャンセル", "ダブルブッキング", "席", "スタッフ別", "何席"]):
        return "RESERVATION"
    
    # 複数店舗の判定
    if any(k in t for k in ["店舗いくつか", "複数店舗", "別店舗", "複数番号", "複数拠点", "全部まとめて", "店舗いくつ"]):
        return "MULTI_STORE"
    
    # 即終了の判定
    if any(k in t for k in ["やめときます", "やめておきます", "また今度", "一旦やめて"]):
        return "END_CALL"

    if any(k in t for k in GREETING_KEYWORDS):
        return "GREETING"
    if any(k in t for k in ["セキュリティ", "個人情報"]) or ("情報" in t and "保存" in t):
        return "FUNCTION"
    if any(k in t for k in ["他の店", "他店", "他の店舗"]):
        return "FUNCTION"
    if "転送" in t and "番号" not in t:
        return "FUNCTION"
    if any(k in t for k in END_CALL_KEYWORDS):
        return "END_CALL"
    if any(k in t for k in PRICE_KEYWORDS):
        return "PRICE"
    if any(k in t for k in SETUP_KEYWORDS):
        return "SETUP"
    if any(k in t for k in FUNCTION_KEYWORDS):
        return "FUNCTION"
    if any(k in t for k in SUPPORT_KEYWORDS):
        return "SUPPORT"
    if any(k in t for k in INQUIRY_KEYWORDS):
        return "INQUIRY"
    return "UNKNOWN"


def select_template_ids(intent: str, text: str) -> list[str]:
    t = normalize_text(text)

    def contains(*keywords: str) -> bool:
        return any(k for k in keywords if k and k in t)

    # ノイズ・聞き取れない
    if intent == "NOT_HEARD":
        return ["0602"]
    
    # HANDOFF関連の意図判定
    if intent == "HANDOFF_YES":
        return ["081", "082"]
    if intent == "HANDOFF_NO":
        return ["086", "087"]
    
    # 営業電話
    if intent == "SALES_CALL":
        if contains("営業", "はい営業"):
            return ["094", "088"]
        return ["093"]
    
    # AI電話の件
    if intent == "AI_CALL_TOPIC":
        return ["0600"]

    if intent == "AI_IDENTITY":
        return ["023_AI_IDENTITY"]

    # システム説明
    if intent == "SYSTEM_EXPLAIN":
        return ["020"]

    # 混雑
    if intent == "BUSY":
        return ["090"]

    # 折り返しリクエスト
    if intent == "CALLBACK_REQUEST":
        return ["0601"]
    
    # 設定難易度
    if intent == "SETUP_DIFFICULTY":
        return ["0603"]

    # 方言
    if intent == "DIALECT":
        return ["066"]

    # 割り込み
    if intent == "INTERRUPT":
        return ["065"]

    # 予約機能
    if intent == "RESERVATION":
        return ["070"]

    # 複数店舗
    if intent == "MULTI_STORE":
        return ["069"]

    if intent == "GREETING":
        return ["004"]

    # システムについての問い合わせ（優先度高い）
    if intent == "SYSTEM_INQUIRY":
        # システムについての問い合わせには、まず006_SYSで確認し、ユーザーの応答を待つ
        # 0603は、ユーザーが設定難易度について質問した場合（SETUP_DIFFICULTYインテント）にのみ返す
        return ["006_SYS"]

    if intent == "INQUIRY":
        return ["006"]

    if intent == "PRICE":
        return ["040"]

    if intent == "SETUP":
        return ["060"]

    if intent == "FUNCTION":
        return ["023"]

    if intent == "SUPPORT":
        if contains("不具合", "故障", "エラー", "障害"):
            return ["0285"]
        return ["0284"]

    if intent == "END_CALL":
        return ["086"]
    
    # HANDOFF_REQUEST の場合、0604を返す
    if intent == "HANDOFF_REQUEST":
        return ["0604"]
    
    # UNKNOWN intent の場合
    if intent == "UNKNOWN":
        return ["114"]

    return ["110"]


def get_response_template(template_id: str) -> str:
    cfg = TEMPLATE_CONFIG.get(template_id)
    if not cfg:
        return ""
    return cfg.get("text", "")


def get_template_config(template_id: str) -> dict | None:
    """テンプレIDに対応する設定辞書を返す"""
    return TEMPLATE_CONFIG.get(template_id)
