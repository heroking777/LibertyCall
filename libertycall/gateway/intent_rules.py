from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

TEMPLATE_CONFIG: dict[str, dict] = {
    "003": {"text": "はい。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "004": {"text": "もしもし。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "005": {"text": "ありがとうございます。どのようなご用件でしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "006": {"text": "導入のご相談でよろしかったでしょうか？", "voice": "ja-JP-Neural2-B", "rate": 1.1, "wait_time_after": 1.8},
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
    "023_AI_IDENTITY": {"text": "はい、私がAIで自動応答させていただいております。内容によっては担当者におつなぎする場合もございますが、わかる範囲でご案内いたします。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
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
    "085": {"text": "ほかに気になる点はありますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "086": {"text": "お電話ありがとうございました。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "087": {"text": "また何かあればいつでもご相談くださいね。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
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
    "089": {"text": "ありがとうございます。ちなみに、どのあたりがご不安でしたか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "090": {"text": "かしこまりました。どこか気になる点や迷っている部分はございますか？", "voice": "ja-JP-Neural2-B", "rate": 1.1},
    "110": {"text": "もしもし？お声が遠いようです。もう一度お願いします。", "voice": "ja-JP-Neural2-B", "rate": 1.0, "wait_time_after": 3.0},
    "111": {"text": "お電話聞こえていますか？", "voice": "ja-JP-Neural2-B", "rate": 1.0, "wait_time_after": 3.0},
    "112": {"text": "お声が確認できませんので、このまま切らせていただきます。", "voice": "ja-JP-Neural2-B", "rate": 1.0, "wait_time_after": 1.0, "auto_hangup": True},
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
    "0605": {"text": "現在担当者が不在のため、このままAIがご案内いたします。ご質問をお聞かせください。", "voice": "ja-JP-Neural2-B", "rate": 1.1},
}

GREETING_KEYWORDS = ["もしもし", "こんにちは", "こんばんは", "おはよう", "はじめまして"]

# 人間オペレーターへの接続を希望する表現を検出するためのキーワード群

# ハンドオフ名詞（人に変わりたい系）
HANDOFF_NOUNS = [
    "オペレーター", "オペレータ", "オペ", "オペさん",
    "担当", "担当者", "たんとうしゃ", "担当の者", "当者",
    "人間", "人", "ひと", "にんげん", "スタッフ", "社員", "社員の人",
    "窓口", "窓口の人",
]

# ハンドオフ動詞（つなぐ・代わる系）
# 注意: 正規化処理で「繋いで」→「つないで」に統一されるため、判定時は「つないで」で統一
HANDOFF_VERBS = [
    "つないで", "代わって", "替わって", "変わって",
    "出てもらって", "出てください", "回して", "まわして",
]

# 依頼表現（お願いします / ください 等）
HANDOFF_REQUEST_PHRASES = [
    "お願いします", "お願い", "ください",
    "もらえますか", "してほしい",
]

# 既存の HANDOFF_REQUEST_KEYWORDS（後方互換性のため保持）
HANDOFF_REQUEST_KEYWORDS = [
    "担当者",
    "たんとうしゃ",
    "担当の者",
    "当者",
    "人間",
    "オペレーター",
    "ひとにつないで",
    "人につないで",
    "繋いで",
    "つないで",
    "繋いでほしい",
    "つないでほしい",
    "回せ",
    "まわせ",
    "回してほしい",
    "まわしてほしい",
    "人に代わって",
    "ひとに代わって",
    "人に変わって",
    "ひとに変わって",
    "代わってほしい",
    "変わってほしい",
    "人と話したい",
    "ひとと話したい",
    "人と話せますか",
    "ひとと話せますか",
]

# 動作確認想定フレーズ（以下のような表現が HANDOFF_REQUEST になる想定）:
# - 「あのオペレーターと変わってください。」
# - 「オペレーターに繋いでください。」
# - 「人間に代わってもらっていいですか？」
# - 「人についてください。」
# - 「人間に詰めてもらっていいですか？」
INQUIRY_KEYWORDS = ["ホームページ", "hp", "lp", "メール", "dm", "導入", "しすてむ", "システム", "サービス", "詳しく", "案内", "相談"]
PRICE_KEYWORDS = ["金額", "料金", "値段", "月額", "費用", "初期費用", "最低契約", "解約", "返金", "無料", "トライアル", "効果", "コスト", "削減", "人件費", "ストレス"]
SETUP_KEYWORDS = ["導入したら", "いつから", "どれくらい", "どうやって", "パソコン", "pc", "スマホ", "電話番号", "転送", "環境", "すぐ使える", "セットアップ"]
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
    "はいはい",
    "ええ",
    "お願いします",
    "お願い",
    "承知",
    "大丈夫です",
    "はいお願いします",
    "はい、お願いします",
]

NO_KEYWORDS = [
    "結構",
    "大丈夫",
    "必要ない",
    "いりません",
    "間に合ってます",
]

# ハンドオフ確認時のNO判定用キーワード（CLOSING_NO_KEYWORDS相当）
HANDOFF_NO_KEYWORDS = [
    "今日はいい",
    "今日は聞くだけ",
    "今日は聞くだけなんで",
    "また考える",
    "また考えます",
    "検討する",
    "やめとく",
    "やめておく",
    "また今度",
    "不要",
    "いりません",
    "結構です",
    "けっこうです",
    "大丈夫です",
    "遠慮します",
    "やめます",
    "また連絡",
    "いらない",
    "やっぱりいい",
    "やっぱりいいです",
]

# 温度の低いリード（検討中・迷っている）を検出するキーワード
LOW_INTENT_KEYWORDS = [
    "いやまだそこまでは",
    "まだ検討中",
    "様子を見てる",
    "今のところ考えてない",
    "導入までは考えてない",
    "検討してるところ",
    "迷っている",
    "まだ決めてない",
    "検討中です",
    "考え中",
    "様子見",
    "まだそこまでは",
    "そこまでは考えてない",
    "まだ考えてない",
]


def normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.lower()
    normalized = normalized.replace(" ", "").replace("　", "")
    return normalized


def normalize_asr_variants(text: str) -> str:
    """ASR誤認識の補正（「詰めて」→「つないで」など）"""
    if not text:
        return ""
    
    replacements = [
        # 基本的な表記統一
        ("にんげん", "人間"),
        ("ひと", "人"),
        ("かわって", "変わって"),
        ("かわて", "変わって"),
        ("かわつて", "変わって"),
        
        # ASR誤認識パターン
        ("詰めて", "つないで"),
        ("つめて", "つないで"),
        ("ついて", "つないで"),
        ("繋ない", "つないで"),
        ("繋いでない", "つないで"),
        ("つないでない", "つないで"),
        
        # 表記統一（漢字→ひらがな）
        ("繋いで", "つないで"),
        ("繋げて", "つないで"),
    ]
    
    result = text
    for src, dst in replacements:
        result = result.replace(src, dst)
    return result


# ===== 意図判定のヘルパー関数 =====

def _has_handoff_intent(text: str) -> bool:
    """ハンドオフ意図があるか判定（統一版）"""
    t = normalize_text(text)
    
    # パターン1: 名詞 + 動詞/依頼表現
    has_noun = any(noun in t for noun in HANDOFF_NOUNS)
    has_verb = any(verb in t for verb in HANDOFF_VERBS)
    has_request = any(phrase in t for phrase in HANDOFF_REQUEST_PHRASES)
    
    if has_noun and (has_verb or has_request):
        return True
    
    # パターン2: 動詞のみでも文脈によってはハンドオフ
    # 「代わって」「つないで」単体
    if any(verb in t for verb in ["代わって", "変わって", "つないで", "回して", "まわして"]):
        return True
    
    # パターン3: 既存のHANDOFF_REQUEST_KEYWORDSもチェック（後方互換性）
    if any(kw in t for kw in HANDOFF_REQUEST_KEYWORDS):
        return True
    
    # パターン4: 「担当/当者 + つな/繋/回し」パターン
    if ("担当" in t or "当者" in t) and ("つな" in t or "繋" in t or "回して" in t or "まわして" in t or "回し" in t or "回せ" in t):
        return True
    
    # パターン5: 「人/ひと/にんげん + 代わ/変わ/話したい/出てほしい/回し」パターン
    if ("人" in t or "ひと" in t or "にんげん" in t) and (
        "代わ" in t or "変わ" in t or "かわ" in t
        or "話したい" in t or "はなしたい" in t
        or "話せますか" in t or "はなせますか" in t
        or "出てほしい" in t or "でてほしい" in t
        or "回し" in t or "回せ" in t or "まわし" in t or "まわせ" in t
    ):
        return True
    
    # パターン6: 「担当者/人間 + お願い」パターン
    if (("担当" in t or "当者" in t or "人" in t or "ひと" in t or "にんげん" in t) 
        and ("お願い" in t or "おねがい" in t)):
        return True
    
    return False


def _has_inquiry_intent(text: str) -> bool:
    """問い合わせ意図があるか判定"""
    t = normalize_text(text)
    
    # ホームページ関連
    if any(p in t for p in ["ホームページ", "ﾎｰﾑﾍﾟｰｼﾞ", "サイト", "さいと", "hp", "ｈｐ"]):
        return True
    
    # メール関連
    if any(k in t for k in ["メール", "メイル", "メールの", "メール来て", "メール来てた", "メール来てたんですけど"]):
        return True
    
    # システム・サービス
    if any(k in t for k in ["システム", "サービス"]):
        return True
    
    # 資料・カタログ
    if any(k in t for k in ["資料", "カタログ"]):
        return True
    
    # 見積
    if any(k in t for k in ["見積", "見積もり"]):
        return True
    
    # 料金・金額
    if any(k in t for k in ["料金", "金額", "費用", "プラン"]):
        return True
    
    # 導入・相談
    if any(k in t for k in ["導入", "相談", "問い合わせ", "お問い合わせ"]):
        return True
    
    # INQUIRY_KEYWORDS
    if any(k in t for k in INQUIRY_KEYWORDS):
        return True
    
    return False


def _is_greeting(text: str) -> bool:
    """挨拶か判定"""
    t = normalize_text(text)
    
    # 名乗りフレーズ
    if any(phrase in t for phrase in ["と言います", "といいます", "と申します"]):
        return True
    
    # 挨拶キーワード
    if any(kw in t for kw in GREETING_KEYWORDS):
        # 「もしもし」の場合は短い発話または名乗りがある場合のみ
        if "もしもし" in t:
            return len(t) <= 8 or "と言います" in t or "といいます" in t
        return True
    
    return False


def _is_ack_response(text: str) -> bool:
    """肯定応答（はい、お願いしますなど）か判定"""
    t = normalize_text(text)
    
    # パターンマッチ
    ack_patterns = [
        r"^はい[。\.]?$",
        r"^はいはい[。\.]?$",
        r"^はい[、,，]?お願いします.*",
        r"^はいお願いします.*",
        r"^お願いします.*",
    ]
    
    if any(re.match(pattern, t) for pattern in ack_patterns):
        return True
    
    # フレーズマッチ
    ack_phrases = [
        "はい",
        "はいはい",
        "ええ",
        "うん",
        "お願いします",
        "お願い",
    ]
    
    if any(t == phrase or t.startswith(phrase) for phrase in ack_phrases):
        return True
    
    return False


def _is_noise(text: str) -> bool:
    """ノイズ・聞き取れない発話か判定"""
    t = normalize_text(text)
    
    # ノイズ語
    if any(noise in t for noise in ["ゴニョゴニョ", "ごにょごにょ"]):
        return True
    
    # 特殊文字が多い
    special_chars = ["…", "。", "、", ".", ","]
    special_count = sum(t.count(c) for c in special_chars)
    if special_count >= 3:
        return True
    
    return False


def classify_intent(text: str, context: str | None = None) -> str:
    """
    ユーザー発話から意図を分類
    
    Args:
        text: ユーザー発話テキスト
        context: オプションのコンテキスト情報（"handoff_confirming"など）
    
    Returns:
        意図を表す文字列（INQUIRY, HANDOFF_REQUEST, GREETING, etc.）
    """
    if not text:
        return "UNKNOWN"
    
    # 正規化
    text = normalize_asr_variants(text)
    t = normalize_text(text)
    
    logger.debug(f"[INTENT] raw={text!r} normalized={t!r} context={context}")
    
    # ===== ノイズ判定（最優先） =====
    if _is_noise(text):
        logger.info(f"[INTENT] NOT_HEARD: {text!r}")
        return "NOT_HEARD"
    
    # ===== コンテキスト依存の判定 =====
    if context == "handoff_confirming":
        # ハンドオフ確認中は ACK を YES として扱う
        if _is_ack_response(text):
            logger.info(f"[INTENT] HANDOFF_YES (context): {text!r}")
            return "HANDOFF_YES"
        
        # NO キーワード
        if any(kw in t for kw in HANDOFF_NO_KEYWORDS):
            logger.info(f"[INTENT] HANDOFF_NO: {text!r}")
            return "HANDOFF_NO"
    
    # ===== システムについての問い合わせ判定（ハンドオフより優先） =====
    # 「システムについて」という明確な問い合わせを検出（ハンドオフ判定より先に実行）
    if any(kw in t for kw in ["システムについて", "システムの", "システムを", "システムが", "システムに", "システムは", "システムで"]):
        logger.info(f"[INTENT] SYSTEM_INQUIRY: {text!r}")
        return "SYSTEM_INQUIRY"
    
    # ===== ハンドオフ判定 =====
    if _has_handoff_intent(text):
        # 「担当者お願いします」のような明確なリクエスト
        logger.info(f"[INTENT] HANDOFF_REQUEST: {text!r}")
        return "HANDOFF_REQUEST"
    
    # ===== 温度の低いリード（検討中・迷っている）を検出（問い合わせ判定より先に実行） =====
    if any(kw in t for kw in LOW_INTENT_KEYWORDS):
        logger.info(f"[INTENT] INQUIRY_PASSIVE: {text!r}")
        return "INQUIRY_PASSIVE"
    
    # ===== 問い合わせ判定 =====
    if _has_inquiry_intent(text):
        logger.info(f"[INTENT] INQUIRY: {text!r}")
        return "INQUIRY"
    
    # ===== 挨拶判定 =====
    if _is_greeting(text):
        logger.info(f"[INTENT] GREETING: {text!r}")
        return "GREETING"
    
    # ===== その他の意図 =====
    # 営業電話
    if any(kw in t for kw in ["営業", "ご提案", "サービスのご提案"]):
        return "SALES_CALL"
    
    # 料金
    if any(kw in t for kw in PRICE_KEYWORDS):
        return "PRICE"
    
    # 設定
    if any(kw in t for kw in SETUP_KEYWORDS):
        return "SETUP"
    
    # 機能
    if any(kw in t for kw in FUNCTION_KEYWORDS):
        return "FUNCTION"
    
    # サポート
    if any(kw in t for kw in SUPPORT_KEYWORDS):
        return "SUPPORT"
    
    # 終了
    if any(kw in t for kw in END_CALL_KEYWORDS):
        return "END_CALL"
    
    # AI電話の件
    if any(kw in t for kw in ["ai電話", "aiの電話", "aiの件", "ai電話の件"]):
        return "AI_CALL_TOPIC"
    
    # AIの正体に関する質問（「aiがやってるんですかね？」など）
    ai_identity_keywords = [
        "aiがやってる", "aiがやってるんですか", "aiがやってるんですかね",
        "aiですか", "aiが対応", "aiが応答", "aiが話して", "aiがしゃべって",
        "ロボット", "自動応答", "自動で", "aiで", "aiによる", "aiによる応答"
    ]
    if any(kw in t for kw in ai_identity_keywords):
        logger.info(f"[INTENT] AI_IDENTITY: {text!r}")
        return "AI_IDENTITY"
    
    # 設定難易度の判定（より広範囲の表現に対応）
    setup_difficulty_keywords = [
        "設定むずい", "設定難しい", "設定むずかしい", "設定がむずい", "設定が難しい",
        "設定は難しい", "設定はむずい", "設定はむずかしい",
        "設定するの", "設定するのは", "設定するのが",
        "難しい", "むずい", "むずかしい", "難しそう", "むずかしそう"
    ]
    # 「設定」「難しい」などのキーワードが含まれる場合
    if any(k in t for k in setup_difficulty_keywords):
        # 「システムの設定」「この設定」などの文脈がある場合、または「設定」と「難しい」の両方が含まれる場合
        if any(ctx in t for ctx in ["システム", "この", "その", "導入", "初期", "設定"]):
            return "SETUP_DIFFICULTY"
        # 「設定」と「難しい」の両方が含まれる場合
        if "設定" in t and any(diff in t for diff in ["難しい", "むずい", "むずかしい", "難し", "むずかし"]):
            return "SETUP_DIFFICULTY"
    
    # システム説明
    if any(kw in t for kw in ["どういうシステム", "どんなシステム", "どういうサービス", "どんなサービス", "これどういう", "どういう"]):
        return "SYSTEM_EXPLAIN"
    
    # 混雑
    if any(kw in t for kw in ["混んでます", "混んでる", "込み合って", "混雑", "混ん"]):
        return "BUSY"
    
    # 折り返し
    if any(kw in t for kw in ["折り返し", "折り返して", "かけ直し", "かけなおし", "折り返しもらえ"]):
        return "CALLBACK_REQUEST"
    
    # 方言
    if any(kw in t for kw in ["関西弁", "方言", "イントネーション"]):
        return "DIALECT"
    
    # 割り込み
    if any(kw in t for kw in ["口挟ん", "割り込ん", "途中で話しても", "途中で口挟ん", "口挟んだり"]):
        return "INTERRUPT"
    
    # 予約機能
    if any(kw in t for kw in ["予約", "キャンセル", "ダブルブッキング", "席", "スタッフ別", "何席"]):
        return "RESERVATION"
    
    # 複数店舗
    if any(kw in t for kw in ["店舗いくつか", "複数店舗", "別店舗", "複数番号", "複数拠点", "全部まとめて", "店舗いくつ"]):
        return "MULTI_STORE"
    
    # ===== デフォルト =====
    logger.info(f"[INTENT] UNKNOWN: {text!r}")
    return "UNKNOWN"


def interpret_handoff_reply(raw_text: str, retry_count: int = 0) -> str:
    """
    ハンドオフ確認時の返答を解釈
    
    Args:
        raw_text: ユーザー発話
        retry_count: リトライ回数（0なら初回）
    
    Returns:
        HANDOFF_YES / HANDOFF_NO / UNKNOWN
    """
    if not raw_text:
        return "UNKNOWN"
    
    # コンテキスト付きで意図判定
    intent = classify_intent(raw_text, context="handoff_confirming")
    
    if intent == "HANDOFF_YES":
        return "HANDOFF_YES"
    
    if intent == "HANDOFF_NO":
        return "HANDOFF_NO"
    
    # UNKNOWN の場合、retry によって振る舞いを変える
    # （この判定は ai_core 側で行うのが望ましい）
    return "UNKNOWN"


def select_template_ids(intent: str, text: str) -> list[str]:
    t = normalize_text(text)

    def contains(*keywords: str) -> bool:
        return any(k for k in keywords if k and k in t)

    # ノイズ・聞き取れない
    if intent == "NOT_HEARD":
        # 【追加】0602 を選んだタイミングのログ
        logger.warning(
            "[NLG_DEBUG] choose_tpl0602 call_id=%s reason=%s state=%r",
            "GLOBAL_CALL",  # select_template_ids には call_id が渡されていないため
            "NOT_HEARD",
            {"intent": intent, "text": text, "normalized": t},
        )
        return ["0602"]
    
    # HANDOFF関連の意図判定
    if intent == "HANDOFF_YES":
        # YESの場合は空リストを返す（ai_core側で081+082を返す）
        return []
    if intent == "HANDOFF_NO":
        # NOの場合は空リストを返す（ai_core側で086+087を返す）
        return []
    
    # 営業電話
    if intent == "SALES_CALL":
        if contains("営業", "はい営業"):
            return ["094", "088"]
        return ["093"]
    
    # AI電話の件
    if intent == "AI_CALL_TOPIC":
        return ["0600"]
    
    # AIの正体に関する質問
    if intent == "AI_IDENTITY":
        return ["023_AI_IDENTITY"]

    # システム説明
    if intent == "SYSTEM_EXPLAIN":
        return ["020", "023", "021", "085"]

    # 混雑
    if intent == "BUSY":
        return ["090", "098"]

    # 折り返しリクエスト
    if intent == "CALLBACK_REQUEST":
        return ["0601"]
    
    # 設定難易度
    if intent == "SETUP_DIFFICULTY":
        return ["0603"]
    
    # AI電話の件
    if intent == "AI_CALL_TOPIC":
        return ["0600"]
    
    # 設定難易度
    if intent == "SETUP_DIFFICULTY":
        return ["0603"]

    # 方言
    if intent == "DIALECT":
        return ["066", "085"]

    # 割り込み
    if intent == "INTERRUPT":
        return ["065", "085"]

    # 予約機能
    if intent == "RESERVATION":
        if contains("ダブルブッキング"):
            return ["071", "085"]
        if contains("席", "何席", "席数"):
            return ["072", "085"]
        if contains("スタッフ別", "スタッフ"):
            return ["072", "085"]
        if contains("予約", "変更", "キャンセル", "取れる"):
            return ["070", "085"]
        return ["070", "085"]

    # 複数店舗
    if intent == "MULTI_STORE":
        return ["069", "085"]

    if intent == "GREETING":
        return ["004", "005"]

    # システムについての問い合わせ（優先度高い）
    if intent == "SYSTEM_INQUIRY":
        # システムについての問い合わせには、まず006_SYSで確認し、ユーザーの応答を待つ
        # 0603は、ユーザーが設定難易度について質問した場合（SETUP_DIFFICULTYインテント）にのみ返す
        return ["006_SYS"]
    
    if intent == "INQUIRY":
        # 【システム問い合わせ用テンプレ分岐追加】「システム」という語を含む場合は006_SYSを使用
        if "システム" in t:
            return ["006_SYS"]
        if contains("ホームページ", "hp", "lp", "dm", "メール", "メッセージ"):
            return ["006"]
        if contains("システム導入したいねんけど", "入れたいねんけど"):
            return ["006"]
        if contains("導入", "入れたい", "導入したい", "いれたい"):
            return ["006", "010"]
        if contains("飲食", "美容", "医療", "クリニック", "小規模", "小さい店", "他の店", "導入実績"):
            return ["0280", "0281", "0283"]
        return ["006", "010"]
    
    # 温度の低いリード（検討中・迷っている）への対応
    if intent == "INQUIRY_PASSIVE":
        # 089または090をランダムで返す（実装時はrandom.choiceを使用）
        import random
        return random.choice([["089"], ["090"]])

    if intent == "PRICE":
        if contains("初期費用"):
            return ["042"]
        if contains("最低契約", "最低期間"):
            return ["045"]
        if contains("解約"):
            return ["046"]
        if contains("トライアル", "初月無料", "無料", "返金"):
            return ["029"]
        if contains("人件費", "コスト", "削減", "効果"):
            return ["049", "048", "047"]
        if contains("ストレス"):
            return ["048"]
        if contains("金額", "料金", "月額", "値段", "費用"):
            return ["040"]
        return ["040"]

    if intent == "SETUP":
        if contains("すぐ使える", "いつから", "どれくらい", "導入したら"):
            return ["060"]
        if contains("転送先番号"):
            return ["061"]
        if contains("どうやって", "パソコン", "スマホ", "電話番号", "番号変える", "環境"):
            return ["061"]
        return ["061"]

    if intent == "FUNCTION":
        if contains("セキュリティ", "個人情報") or ("情報" in t and "保存" in t):
            return ["063"]
        if contains("間違", "クレーム"):
            return ["021"]
        if "転送" in t and "番号" not in t:
            return ["023"]
        if contains("転送", "引き継ぎ", "ダブルブッキング"):
            return ["023"]
        if contains("個人情報", "セキュリティ", "録音", "情報"):
            return ["063"]
        if contains("他の店", "他店", "他の店舗"):
            return ["0280", "0283"]
        if contains("飲食", "美容", "医療", "店舗", "導入実績", "小規模"):
            return ["0280", "0281", "0283"]
        if contains("サポート", "不具合"):
            return ["0284"]
        return ["026"]

    if intent == "SUPPORT":
        if contains("不具合", "故障", "エラー", "障害"):
            return ["0285"]
        return ["0284"]

    if intent == "END_CALL":
        return ["086", "087", "088"]
    
    # HANDOFF_REQUEST / UNKNOWN の場合、空リストを返す（0604は ai_core 側で出す）
    if intent in ("UNKNOWN", "HANDOFF_REQUEST"):
        return []

    return ["110"]


def get_response_template(template_id: str) -> str:
    cfg = TEMPLATE_CONFIG.get(template_id)
    if not cfg:
        return ""
    return cfg.get("text", "")


def get_template_config(template_id: str) -> dict | None:
    """テンプレIDに対応する設定辞書を返す"""
    return TEMPLATE_CONFIG.get(template_id)


def test_classify_intent():
    """
    期待される挙動のテスト（doctest形式）
    
    >>> test_classify_intent()
    """
    test_cases = [
        # 問い合わせ系 → INQUIRY
        ("あ、もしもしホームページ見たんですけど。", "INQUIRY"),
        ("ホームページ見て電話したんですけど。", "INQUIRY"),
        ("あ、メール来てたんですけど。", "INQUIRY"),
        ("システムについて聞きたいんですけど。", "INQUIRY"),
        ("メール来てたんですけど", "INQUIRY"),
        
        # GREETING / 名乗り → GREETING
        ("あ、もしもし 山田と言います。", "GREETING"),
        ("もしもし", "GREETING"),
        ("こんにちは", "GREETING"),
        
        # ハンドオフ系 → HANDOFF_REQUEST / HANDOFF_YES
        ("人間に繋いでください。", "HANDOFF_REQUEST"),
        ("人間に代わってもらえますか。", "HANDOFF_REQUEST"),
        ("担当者につないで", "HANDOFF_REQUEST"),
        ("あ、人間に変わってもらっていいですか？", "HANDOFF_REQUEST"),
        # 新しい想定フレーズ（強化された判定ロジックで検出される想定）
        ("あのオペレーターと変わってください。", "HANDOFF_REQUEST"),
        ("オペレーターに繋いでください。", "HANDOFF_REQUEST"),
        ("人間に代わってもらっていいですか？", "HANDOFF_REQUEST"),
        ("人についてください。", "HANDOFF_REQUEST"),
        ("人間に詰めてもらっていいですか？", "HANDOFF_REQUEST"),
        ("担当に繋いでください。", "HANDOFF_REQUEST"),
        ("オペレーターに代わってもらっていいですか？", "HANDOFF_REQUEST"),
        ("スタッフに繋いでください。", "HANDOFF_REQUEST"),
        ("はい。", "HANDOFF_YES"),
        ("はい、お願いします。", "HANDOFF_YES"),
        ("お願いします", "HANDOFF_YES"),
        
        # NOT_HEARD → 本当に意味が取れないときだけ
        ("あー…えっと…ああえ！", "NOT_HEARD"),
        ("ゴニョゴニョ", "NOT_HEARD"),
    ]
    
    results = []
    for text, expected in test_cases:
        actual = classify_intent(text)
        status = "✓" if actual == expected else "✗"
        results.append(f"{status} {text!r} → {actual} (expected: {expected})")
        if actual != expected:
            print(f"FAIL: {text!r} → {actual} (expected: {expected})")
    
    print("\n".join(results))
    return results


def test_select_template_ids():
    """
    テンプレート選択のテスト
    
    >>> test_select_template_ids()
    """
    test_cases = [
        # システム系問い合わせ → 006_SYS
        ("システムについて聞きたいんですけど。", "INQUIRY", ["006_SYS"]),
        ("システムの使い方を教えてください", "INQUIRY", ["006_SYS"]),
        
        # ホームページ/メール系問い合わせ → 006
        ("ああ、もしもしホームページ見たんですけど。", "INQUIRY", ["006"]),
        ("あ、メール来たんですけど。", "INQUIRY", ["006"]),
    ]
    
    results = []
    for text, intent, expected_tpl in test_cases:
        actual_tpl = select_template_ids(intent, text)
        status = "✓" if actual_tpl == expected_tpl else "✗"
        results.append(f"{status} {text!r} intent={intent} → tpl={actual_tpl} (expected: {expected_tpl})")
        if actual_tpl != expected_tpl:
            print(f"FAIL: {text!r} intent={intent} → tpl={actual_tpl} (expected: {expected_tpl})")
    
    print("\n".join(results))
    return results


if __name__ == "__main__":
    # テスト実行
    print("=== classify_intent テスト ===")
    test_classify_intent()
    print("\n=== select_template_ids テスト ===")
    test_select_template_ids()
