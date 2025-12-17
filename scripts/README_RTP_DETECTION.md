# RTPポート検出スクリプト 使い方

## 概要

通話が短時間（10秒以内）で切れる場合でも、確実にRTPポート情報を取得するためのスクリプトです。

## スクリプト一覧

### 1. `detect_rtp_port.sh` - 手動実行版（基本版）

通話中に手動で実行して、チャンネル情報とRTPポートを取得します。

### 1-2. `detect_rtp_port_enhanced.sh` - 手動実行版（改良版）⭐ 推奨

基本版を改良し、接続の安定化、エラーハンドリング、再接続機能を強化したバージョンです。

**主な改善点:**
- Event Socket接続の自動再接続機能（最大5回）
- 各コマンド実行時のエラーハンドリング強化
- 接続失敗時の詳細なエラーメッセージ
- 双方向RTP確認用のtcpdumpコマンドを自動生成

**使い方:**
```bash
# 通話開始後、すぐに実行
/opt/libertycall/scripts/detect_rtp_port_enhanced.sh
```

**特徴:**
- 接続エラー時の自動再接続（最大5回試行）
- 各コマンド実行時のエラーハンドリング
- より詳細なエラーメッセージとトラブルシューティング情報
- 双方向RTP確認用のtcpdumpコマンドを自動生成

---

### 2. `auto_detect_rtp.sh` - 完全自動化版（基本版）

FreeSWITCHのチャンネル数を監視し、新しい通話が開始されたら自動的にRTPポート情報を取得します。

### 2-2. `auto_detect_rtp_enhanced.sh` - 完全自動化版（改良版）⭐ 推奨

基本版を改良し、接続の安定化、エラーハンドリング、再接続機能を強化したバージョンです。

**主な改善点:**
- 定期的な接続チェック（10回ごと）
- 接続エラー時の自動再接続機能
- エラーカウントによる接続状態の監視
- より詳細なログ出力

**使い方:**
```bash
# バックグラウンドで実行
/opt/libertycall/scripts/auto_detect_rtp_enhanced.sh

# または、systemdサービスとして実行（推奨）
sudo systemctl start rtp-detection
```

**使い方:**
```bash
# 通話開始後、すぐに実行
/opt/libertycall/scripts/detect_rtp_port.sh
```

**特徴:**
- 複数回試行（最大3回）して確実に情報を取得
- 通話が短くても、1回の実行で情報を取得可能
- RTPポート番号を自動抽出してtcpdumpコマンドを表示

**出力例:**
```
=== RTP Port Detection Script - 2025-12-17 15:51:00 ===
[INFO] FreeSWITCH Event Socket に接続しました
[試行 1/3] show channels 実行中...
[SUCCESS] アクティブなチャンネルを検出しました
=== チャンネル情報 ===
uuid,direction,created,created_epoch,name,state,...
8140bb73-dcd5-44cc-bdcf-b176d128c211,inbound,...
=== RTPポート情報取得中 ===
RTP Local Port: 7182
RTP Remote IP: 61.213.230.90
RTP Remote Port: 19896
=== tcpdump コマンド例 ===
sudo tcpdump -n -i any udp port 7182 -vvv -c 20
```

---

### 2. `auto_detect_rtp.sh` - 完全自動化版

FreeSWITCHのチャンネル数を監視し、新しい通話が開始されたら自動的にRTPポート情報を取得します。

**使い方:**
```bash
# バックグラウンドで実行
/opt/libertycall/scripts/auto_detect_rtp.sh

# または、systemdサービスとして実行（推奨）
sudo systemctl start rtp-detection
```

**特徴:**
- 通話開始を自動検出
- ログファイルに自動保存（`/opt/libertycall/logs/rtp_detection_YYYYMMDD_HHMMSS.log`）
- 複数の通話にも対応
- Ctrl+Cで終了

**ログファイルの場所:**
```
/opt/libertycall/logs/rtp_detection_YYYYMMDD_HHMMSS.log
```

---

## 使用例

### ケース1: 手動で1回だけ取得したい場合（推奨：改良版）

```bash
# 通話開始後、すぐに実行（改良版：接続エラー時の自動再接続機能付き）
/opt/libertycall/scripts/detect_rtp_port_enhanced.sh

# または、基本版
/opt/libertycall/scripts/detect_rtp_port.sh
```

### ケース2: 継続的に監視したい場合（推奨：改良版）

```bash
# ターミナル1: 監視スクリプトを実行（改良版：接続エラー時の自動再接続機能付き）
/opt/libertycall/scripts/auto_detect_rtp_enhanced.sh

# または、基本版
/opt/libertycall/scripts/auto_detect_rtp.sh

# ターミナル2: 通話を開始
# 自動的にRTPポート情報が取得されます
```

### ケース3: tcpdumpでRTPパケットを確認

```bash
# 1. RTPポートを取得（改良版推奨）
/opt/libertycall/scripts/detect_rtp_port_enhanced.sh

# 2. 出力されたtcpdumpコマンドを実行
# 改良版では、双方向RTP確認用のコマンドも自動生成されます
sudo tcpdump -n -i any udp port 7182 -vvv -c 20

# 双方向確認（改良版の出力に含まれます）
# FreeSWITCH → Rakuten の送信を確認
sudo tcpdump -n -i any 'udp port 7182 and src host 160.251.170.253' -vvv -c 20

# Rakuten → FreeSWITCH の受信を確認
sudo tcpdump -n -i any 'udp port 7182 and dst host 160.251.170.253' -vvv -c 20
```

---

## 改良版スクリプトの主な改善点

### 接続の安定化

- **自動再接続機能**: Event Socket接続が失敗した場合、最大5回まで自動的に再接続を試みます
- **定期的な接続チェック**: 自動検出版では、定期的に接続状態を確認します
- **エラーカウント**: 連続したエラーをカウントし、一定回数以上で再接続を試みます

### エラーハンドリングの強化

- **詳細なエラーメッセージ**: 接続失敗時に、確認すべき項目を表示します
- **各コマンド実行時のエラーハンドリング**: 各コマンド実行時にエラーが発生した場合、自動的に再接続を試みます
- **タイムアウト処理**: 接続タイムアウト時の適切な処理

### 使いやすさの向上

- **双方向RTP確認コマンド**: tcpdumpコマンドを自動生成し、送信・受信の両方向を確認できます
- **より詳細なログ**: 自動検出版では、より詳細なログを出力します

---

## トラブルシューティング

### Event Socketに接続できない場合（改良版スクリプト推奨）

改良版スクリプトは、接続エラー時に自動的に再接続を試みます。それでも接続できない場合：

```bash
# FreeSWITCHの状態を確認
sudo systemctl status freeswitch

# ポート8021がLISTENしているか確認
sudo netstat -tulnp | grep 8021

# Event Socketの設定を確認
cat /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml
```

### チャンネルが見つからない場合

- 通話が実際に開始されているか確認
- `fs_cli -x "show channels"` で手動確認
- 通話開始から少し時間を置いてから実行

### RTPポート情報が取得できない場合

- 通話が確立されているか確認（RTPネゴシエーションが完了している必要がある）
- `uuid_media <UUID>` コマンドで手動確認
- FreeSWITCHのログを確認: `sudo tail -f /usr/local/freeswitch/log/freeswitch.log`

---

## 注意事項

1. **タイミング**: 通話開始直後はRTPネゴシエーションが完了していない可能性があります。1-2秒待ってから実行することを推奨します。

2. **複数チャンネル**: 複数の通話が同時に存在する場合、最初のチャンネルの情報のみを取得します。

3. **ログファイル**: `auto_detect_rtp.sh` はログファイルを自動生成します。定期的にクリーンアップすることを推奨します。

---

## 関連ファイル

- `/opt/libertycall/scripts/detect_rtp_port.sh` - 手動実行版
- `/opt/libertycall/scripts/auto_detect_rtp.sh` - 完全自動化版
- `/opt/libertycall/logs/rtp_detection_*.log` - 自動検出ログ

