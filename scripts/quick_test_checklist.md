# ASR統合テスト クイックチェックリスト

## ✅ 事前確認（テスト実行前）

### 1. FreeSWITCH接続確認
```bash
cd /opt/libertycall
./scripts/test_freeswitch_connection.sh
```

**期待される結果:**
- ✅ FreeSWITCHステータス: UP
- ✅ Sofia SIPステータス: RUNNING
- ✅ ESLポート8021: LISTEN

### 2. Python環境確認
```bash
cd /opt/libertycall
python3 scripts/test_asr_handler.py
```

**期待される結果:**
- ✅ ESL接続: PASS
- ✅ Google認証: PASS
- ✅ ASRハンドラー: PASS
- ✅ 音声ファイル: PASS

### 4. Google Cloud API確認
```bash
gcloud auth list
gcloud services list | grep speech
```

**期待される結果:**
- ✅ speech.googleapis.com: ENABLED

---

## 🧪 着信テスト手順

### Step 0: 環境変数設定（未設定の場合）
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json"
```

### Step 1: ログ監視開始
```bash
cd /opt/libertycall
./scripts/monitor_asr_test.sh
```

または、ワンライナー:
```bash
sudo tail -Fn0 /usr/local/freeswitch/log/freeswitch.log | grep -E "playback|ASR|hangup" & tail -Fn0 /tmp/gateway_*.log | grep -E "ASRHandler|GoogleStreamingASR"
```

### Step 2: gateway_event_listener起動確認
```bash
ps aux | grep gateway_event_listener
```

起動していない場合:
```bash
cd /opt/libertycall
python3 gateway_event_listener.py &
```

### Step 3: 着信実行
外部またはSIPアプリから着信

---

## 📊 期待されるログパターン

### 🟢 成功パターン（発話あり）

```
[FreeSWITCH]
playback(/opt/libertycall/clients/000/audio/000_8k.wav)
playback(/opt/libertycall/clients/000/audio/001_8k.wav)
playback(/opt/libertycall/clients/000/audio/002_8k.wav)
CHANNEL_ANSWER UUID=xxx

[Gateway/ASR]
[ASRHandler] Processing incoming call: xxx
[ASRHandler] Google Streaming ASR started
[GoogleStreamingASR] Stream started
STREAMING_FEED: idx=1 dt=20.0ms call_id=xxx len=320 rms=1234
[ASR] 予約をお願いします
[ASRHandler] Response detected: 予約をお願いします
[ASRHandler] Replying: あなたの回答は予約をお願いしますです。
[ASRHandler] Hanging up after response
CHANNEL_HANGUP UUID=xxx
```

### 🟡 無反応パターン（催促→切断）

```
[FreeSWITCH]
playback(000_8k.wav)
playback(001_8k.wav)
playback(002_8k.wav)
CHANNEL_ANSWER UUID=xxx
[ASRHandler] Silence monitoring started
[ASRHandler] Playing reminder 1: /opt/libertycall/clients/000/audio/000-004_8k.wav
playback(000-004_8k.wav)
[ASRHandler] Playing reminder 2: /opt/libertycall/clients/000/audio/000-005_8k.wav
playback(000-005_8k.wav)
[ASRHandler] Playing reminder 3: /opt/libertycall/clients/000/audio/000-006_8k.wav
playback(000-006_8k.wav)
[ASRHandler] No response after all reminders, hanging up
CHANNEL_HANGUP UUID=xxx
```

---

## 🔍 トラブルシューティング

### 症状: 即切断する

**確認箇所:**
```bash
# FreeSWITCHのdialplan確認
grep -A 5 "socket\|async" /usr/local/freeswitch/conf/dialplan/public.xml

# gateway_event_listenerのログ確認
tail -f /tmp/gateway_event_listener.log
```

### 症状: ASR結果が出ない

**確認箇所:**
```bash
# Google認証確認
echo $GOOGLE_APPLICATION_CREDENTIALS
ls -l $GOOGLE_APPLICATION_CREDENTIALS

# realtime_gatewayのログ確認
tail -f /tmp/gateway_*.log | grep -E "STREAMING_FEED|ASR"

# ASRハンドラーのログ確認
tail -f /tmp/gateway_*.log | grep -E "ASRHandler|GoogleStreamingASR"
```

### 症状: 音声が流れない

**確認箇所:**
```bash
# 音声ファイル存在確認
ls -lh /opt/libertycall/clients/000/audio/*.wav

# FreeSWITCHのplaybackログ確認
sudo tail -f /usr/local/freeswitch/log/freeswitch.log | grep playback
```

### 症状: 無限ループやハング

**確認箇所:**
```bash
# プロセス確認
ps aux | grep -E "asr_handler|gateway_event_listener|realtime_gateway"

# スレッド確認
pstree -p | grep -E "asr_handler|gateway"
```

---

## 📝 テスト結果記録用テンプレート

```
テスト日時: YYYY-MM-DD HH:MM:SS
テスト者: [名前]

[ ] FreeSWITCH接続: ✅ / ❌
[ ] Python環境: ✅ / ❌
[ ] Google API: ✅ / ❌
[ ] 着信テスト: ✅ / ❌
[ ] ASR認識: ✅ / ❌
[ ] 催促動作: ✅ / ❌
[ ] 切断動作: ✅ / ❌

ログファイル:
- FreeSWITCH: /usr/local/freeswitch/log/freeswitch.log
- Gateway: /tmp/gateway_*.log

問題点・改善点:
[記録]
```

---

## 🚀 次のステップ

テストが成功したら:

1. **応答内容別フロー分岐**の実装
2. **DB連携**（会話ログ記録）
3. **同時通話制限**の実装
4. **DialogFlow連携**（会話ログ転送）

