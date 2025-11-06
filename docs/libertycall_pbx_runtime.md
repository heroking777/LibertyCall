---8<--- START OF FILE ---8<---
# LibertyCall PBX Runtime Memo
（最終更新: 2025-11-06 JST）

## 0. このファイルの目的
このファイルは **LibertyCall（AI電話受付システム）** の  
Asterisk と AGI（音声認識スクリプト）に関する設定・ルールをまとめたメモです。  
ChatGPTの履歴が消えても、この1枚を読めばすぐ再現できるようにします。

---

## 1. 関係ファイルと場所
| ファイル | 説明 |
|-----------|------|
| `/etc/asterisk/extensions.d/zz_incoming_active.conf` | Asteriskのダイヤルプラン（実際に電話の流れを定義） |
| `/var/lib/asterisk/agi-bin/pbx_bridge.py` | AGIスクリプト（音声認識と判断を行う） |
| `/var/lib/asterisk/sounds/ja/` | 音声案内ファイル（greeting, company_name, ask_plain, confirm_transferなど） |
| `/var/spool/asterisk/libertycall/` | 通話録音・留守電の保存場所 |

---

## 2. 電話の流れ（基本動作）
1. **着信 → 再生 → 録音 → AI解析**
   - `incoming-call` コンテキストで音声案内を再生し、録音した音声をAGIへ渡す。
2. **AGI（pbx_bridge.py）で判断**
   - 音声をGoogle Speech-to-Textで認識。
   - 発話内容をもとに `ACTION` 変数を返す。
3. **営業時間内 (10:00〜17:30)**
   - `[decide]` コンテキストで `ACTION` の内容により分岐：
     - `transfer` → 担当者に転送（不在なら留守電へ）
     - `voicemail` → すぐ留守電へ
     - `ai` → 今後の拡張用（AI応答ルート）
4. **営業時間外**
   - `[ahentry]` で自動的に `[vm]`（留守電）へ。
5. **留守電 ([vm])**
   - 「担当者より折り返します」を再生 → 録音保存。

---

## 3. AGIが返す変数（Asteriskへ）
| 変数名 | 内容 |
|---------|------|
| `LAST_TRANSCRIPT` | 音声認識の結果テキスト |
| `TRANSFER_TO` | 転送先番号（あれば） |
| `ACTION` | `transfer` / `voicemail` / `ai`（判断結果） |

---

## 4. 現在の判定ロジック（簡略版）
- 「ホームページ」「お問い合わせ」「資料請求」などの語を含む → `ACTION="transfer"`
- それ以外（例：「折り返しお願いします」など） → `ACTION="voicemail"`

---

## 5. 発信者番号の正規化ルール
Asteriskでは、Rakuten回線などで `CALLERID(num)` が正しく取れない場合があるため：
1. `CALLERID(num)` → ダメなら `P-Asserted-Identity` → ダメなら `From` を読む  
2. +81 や 81 で始まる場合は国内形式 (090/080) に変換  
3. 正規化した番号は `RC_NAT` としてログやスクリプトに渡す

---

## 6. ログ設定
もし `/var/log/asterisk/messages` が無い場合は以下を設定：

`/etc/asterisk/logger.conf`
```

[general]
dateformat=%Y-%m-%d %H:%M:%S

[logfiles]
messages => notice,warning,error,verbose
console  => notice,warning,error

```

再読み込みコマンド：
```

sudo asterisk -rx 'logger reload'

```

ログを見るコマンド：
```

sudo tail -F /var/log/asterisk/messages | egrep -i 'NoOp|pbx_bridge|Dial|Goto|Record|lc_logwrite'

```

---

## 7. 今後の拡張予定（覚書）
- **クライアントごとのルール対応**  
  → `ACTION` の判断を pbx_bridge.py 内で切り替え可能にする。
- **`ai` アクション対応**  
  → AI応答専用ハンドラを追加し、「自動回答で完結」できる仕組みへ。
- **テナント設定ファイル**  
  → `/etc/libertycall/tenant.yml` 等で、転送先や営業時間を個別設定。

---

## 8. 更新ルール
- ChatGPT（GPT-5）は、AsteriskやAGIを変更したら必ずこの `.md` を更新案付きで提示。
- Copilotは、提示された更新案を確認し、Gitにコミット＆プッシュする。
- バックアップ命名：`zz_incoming_active.conf.bak.YYYYMMDD-HHMMSS`

---

## 9. 最終動作確認（Ubuntu VM）
```

sudo asterisk -rx 'dialplan show incoming-call'
sudo asterisk -rx 'dialplan show decide'
sudo asterisk -rx 'dialplan show vm'
ls -l /var/lib/asterisk/agi-bin/pbx_bridge.py
ls -l /var/lib/asterisk/sounds/ja/*.ulaw

```

---

