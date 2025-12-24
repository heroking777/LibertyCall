# ASR統合テスト ワンライナーコマンド集

## 🚀 クイックスタート

### 1. 環境変数設定（初回のみ）
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json"
```

### 2. 事前確認（一括実行）
```bash
cd /opt/libertycall && ./scripts/test_freeswitch_connection.sh && python3 scripts/test_asr_handler.py
```

---

## 📊 ログ監視（着信テスト用）

### FreeSWITCH + Gateway ログ同時監視
```bash
sudo tail -Fn0 /usr/local/freeswitch/log/freeswitch.log | grep -E "playback|ASR|hangup|CHANNEL_ANSWER|CHANNEL_HANGUP" & tail -Fn0 /tmp/gateway_*.log 2>/dev/null | grep -E "ASRHandler|GoogleStreamingASR|STREAMING_FEED|ASR DETECTED"
```

### FreeSWITCHログのみ
```bash
sudo tail -Fn0 /usr/local/freeswitch/log/freeswitch.log | grep -E "playback|ASR|WAIT|hangup"
```

### Gatewayログのみ
```bash
tail -Fn0 /tmp/gateway_*.log | grep -E "ASRHandler|GoogleStreamingASR|STREAMING_FEED"
```

### スクリプト使用（推奨）
```bash
cd /opt/libertycall && ./scripts/monitor_asr_test.sh
```

---

## 🔍 個別確認コマンド

### FreeSWITCHステータス確認
```bash
sudo fs_cli -x "status" && sudo fs_cli -x "sofia status"
```

### ESLポート確認
```bash
sudo netstat -tulnp | grep 8021
```

### Google認証確認
```bash
echo $GOOGLE_APPLICATION_CREDENTIALS && ls -lh $GOOGLE_APPLICATION_CREDENTIALS
```

### 音声ファイル確認
```bash
ls -lh /opt/libertycall/clients/000/audio/*.wav
```

### gateway_event_listener起動確認
```bash
ps aux | grep gateway_event_listener | grep -v grep
```

### ASRハンドラープロセス確認
```bash
ps aux | grep -E "asr_handler|realtime_gateway" | grep -v grep
```

---

## 🧪 テスト実行フロー

### 完全テスト（推奨）
```bash
cd /opt/libertycall && \
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json" && \
./scripts/test_freeswitch_connection.sh && \
python3 scripts/test_asr_handler.py && \
echo "✅ 事前確認完了。着信テストを実行してください。"
```

### 着信テスト実行時
```bash
# ターミナル1: ログ監視
cd /opt/libertycall && ./scripts/monitor_asr_test.sh

# ターミナル2: gateway_event_listener起動確認・起動
ps aux | grep gateway_event_listener || (cd /opt/libertycall && python3 gateway_event_listener.py &)

# ターミナル3: 着信実行
# （外部またはSIPアプリから着信）
```

---

## 🐛 トラブルシューティング用コマンド

### FreeSWITCH再起動
```bash
sudo systemctl restart freeswitch && sleep 2 && sudo fs_cli -x "status"
```

### gateway_event_listener再起動
```bash
pkill -f gateway_event_listener && sleep 1 && cd /opt/libertycall && python3 gateway_event_listener.py &
```

### 全Gatewayプロセス確認・停止
```bash
ps aux | grep -E "realtime_gateway|gateway_event_listener|asr_handler" | grep -v grep && \
pkill -f "realtime_gateway|gateway_event_listener|asr_handler"
```

### ログファイル一覧（最新順）
```bash
ls -lt /tmp/gateway_*.log 2>/dev/null | head -5
```

### 最新のGatewayログをリアルタイム監視
```bash
LATEST=$(ls -t /tmp/gateway_*.log 2>/dev/null | head -1) && [ -n "$LATEST" ] && tail -f "$LATEST" | grep -E "ASRHandler|GoogleStreamingASR|STREAMING_FEED"
```

---

## 📝 ログ検索（過去ログ確認）

### ASR認識結果を検索
```bash
grep -r "ASR\]\|ASR DETECTED" /tmp/gateway_*.log 2>/dev/null | tail -20
```

### 催促再生を検索
```bash
grep -r "Playing reminder\|000-004\|000-005\|000-006" /tmp/gateway_*.log 2>/dev/null | tail -20
```

### 切断イベントを検索
```bash
grep -r "Hanging up\|hangup" /tmp/gateway_*.log 2>/dev/null | tail -20
```

### FreeSWITCHログからplayback履歴を検索
```bash
sudo grep "playback" /usr/local/freeswitch/log/freeswitch.log | tail -20
```

---

## ✅ 成功パターン確認用

### 発話ありパターン（期待されるログ）
```bash
# 以下のキーワードが順番に出現することを確認
grep -E "playback.*000_8k|playback.*001_8k|playback.*002_8k|ASRHandler.*started|ASR\]|ASR DETECTED|Hanging up" /tmp/gateway_*.log 2>/dev/null | tail -10
```

### 無反応パターン（期待されるログ）
```bash
# 以下のキーワードが順番に出現することを確認
grep -E "playback.*000_8k|playback.*001_8k|playback.*002_8k|Playing reminder|No response|hanging up" /tmp/gateway_*.log 2>/dev/null | tail -10
```

---

## 🎯 本番前最終チェック

```bash
cd /opt/libertycall && \
export GOOGLE_APPLICATION_CREDENTIALS="/opt/libertycall/key/google_tts.json" && \
echo "=== 1. FreeSWITCH確認 ===" && \
sudo fs_cli -x "status" | head -3 && \
echo "=== 2. Python環境確認 ===" && \
python3 scripts/test_asr_handler.py | tail -10 && \
echo "=== 3. 音声ファイル確認 ===" && \
ls -lh /opt/libertycall/clients/000/audio/*.wav | wc -l && \
echo "=== 4. gateway_event_listener確認 ===" && \
ps aux | grep gateway_event_listener | grep -v grep && \
echo "✅ すべての確認が完了しました"
```

