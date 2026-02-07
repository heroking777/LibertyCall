# 新規電話番号追加手順

## 概要
LibertyCallシステムに新しい電話番号（クライアント）を追加する手順。

## 前提条件
- FreeSWITCHが稼働中
- SIP認証情報（番号・パスワード）を取得済み

---

## Step 1: SIPゲートウェイ設定

```bash
# 新しいゲートウェイファイルを作成
cat > /usr/local/freeswitch/conf/sip_profiles/external/rakuten_XXX.xml << 'GATEWAY'
<include>
  <gateway name="rakuten_XXX">
    <param name="username" value="[電話番号下8桁]"/>
    <param name="password" value="[パスワード]"/>
    <param name="realm" value="gw-okj.sip.0038.net"/>
    <param name="proxy" value="61.213.230.145"/>
    <param name="register" value="true"/>
    <param name="extension" value="[電話番号下8桁]"/>
  </gateway>
</include>
GATEWAY

# 設定反映
fs_cli -x "reloadxml"
fs_cli -x "sofia profile external restart"

# 登録確認（REGEDになればOK）
fs_cli -x "sofia status gateway rakuten_XXX"
```

---

## Step 2: dialplan更新

`/usr/local/freeswitch/conf/dialplan/public/public_minimal.xml`の正規表現を更新。

**修正箇所（3箇所）**:
- `__catch_all_answer_debug__` extension
- `force_public_entry` extension
- `fallback-libertycall` extension
- `af_fork_58304073` extension

```bash
# 新番号を除外リストに追加
# 例: 58654181を追加する場合
sed -i 's/(?!58304073$|58654181$)/(?!58304073$|58654181$|[新番号]$)/g' \
  /usr/local/freeswitch/conf/dialplan/public/public_minimal.xml

# af_fork extensionの正規表現に新番号を追加
# 例: ^(58304073|58654181)$ → ^(58304073|58654181|[新番号])$
sed -i 's/expression="^(58304073|58654181)$"/expression="^(58304073|58654181|[新番号])$"/' \
  /usr/local/freeswitch/conf/dialplan/public/public_minimal.xml

# 設定反映
fs_cli -x "reloadxml"
```

---

## Step 3: 電話番号マッピング追加

```bash
# phone_mapping.jsonに追加
vi /opt/libertycall/config/phone_mapping.json
```

```json
{
  "58304073": "000",
  "58654181": "001",
  "[新番号]": "[新client_id]"
}
```

---

## Step 4: クライアントフォルダ作成

```bash
# フォルダ構成作成
mkdir -p /opt/libertycall/clients/[client_id]/config
mkdir -p /opt/libertycall/clients/[client_id]/audio

# dialogue_config.json作成
cat > /opt/libertycall/clients/[client_id]/config/dialogue_config.json << 'CONFIG'
{
  "client_name": "[クライアント名]",
  "greeting": "000",
  "patterns": [
    {
      "keywords": ["もしもし", "モシモシ"],
      "response": "001"
    },
    {
      "keywords": ["こんにちは", "こんにちわ"],
      "response": "002"
    }
  ],
  "default_response": "002",
  "timeout_response": "003",
  "no_input_count_limit": 2
}
CONFIG

# voice_list.tsv作成
cat > /opt/libertycall/clients/[client_id]/audio/voice_list_[client_id].tsv << 'VOICE'
000お電話ありがとうございます○○会社です
001もしもし
002ご用件をお伺いします
003用がないのでしたら切りますね
VOICE
```

---

## Step 5: 音声ファイル配置

```bash
# 音声ファイルを配置（8kHz WAV形式）
cp [音声ファイル].wav /opt/libertycall/clients/[client_id]/audio/000.wav
cp [音声ファイル].wav /opt/libertycall/clients/[client_id]/audio/001.wav
# ...

# RAMディスクにもコピー（高速再生用）
cp /opt/libertycall/clients/[client_id]/audio/*.wav /dev/shm/audio/
```

---

## Step 6: 動作確認

```bash
# サービス再起動（必要に応じて）
systemctl restart asr-ws-sink

# ログ監視
tail -f /tmp/ws_sink_debug.log | grep -E "WS_SERVER|client_id"

# 新番号に電話をかけてテスト
# 期待されるログ:
# [WS_SERVER] Got destination_number=[新番号] for uuid=xxx
# [WS_SERVER] Mapped [新番号] -> client_id=[新client_id]
```

---

## ファイル一覧

| ファイル | 用途 |
|---------|------|
| `/usr/local/freeswitch/conf/sip_profiles/external/rakuten_XXX.xml` | SIPゲートウェイ設定 |
| `/usr/local/freeswitch/conf/dialplan/public/public_minimal.xml` | dialplanルーティング |
| `/opt/libertycall/config/phone_mapping.json` | 電話番号→client_idマッピング |
| `/opt/libertycall/clients/[client_id]/config/dialogue_config.json` | 会話フロー設定 |
| `/opt/libertycall/clients/[client_id]/audio/` | 音声ファイル |

---

## トラブルシューティング

### SIPゲートウェイが登録されない
```bash
fs_cli -x "sofia status gateway rakuten_XXX"
# FAILの場合: 認証情報を確認
```

### 着信がルーティングされない
```bash
# FreeSWITCHログで確認
tail -100 /usr/local/freeswitch/log/freeswitch.log | grep "[新番号]"
# dialplanの正規表現を確認
```

### client_idが000のまま
```bash
# phone_mapping.jsonを確認
cat /opt/libertycall/config/phone_mapping.json
# ws_sink.pyのログを確認
tail -f /tmp/ws_sink_debug.log | grep "WS_SERVER"
```

---

## 作成日
2026-02-05
