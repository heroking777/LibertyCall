# RTPポート検出スクリプト 使い方

## 概要

通話が短時間（10秒以内）で切れる場合でも、確実にRTPポート情報を取得するためのスクリプトです。

## スクリプト一覧

### 1. `detect_rtp_port.sh` - 手動実行版

通話中に手動で実行して、チャンネル情報とRTPポートを取得します。

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

### ケース1: 手動で1回だけ取得したい場合

```bash
# 通話開始後、すぐに実行
/opt/libertycall/scripts/detect_rtp_port.sh
```

### ケース2: 継続的に監視したい場合

```bash
# ターミナル1: 監視スクリプトを実行
/opt/libertycall/scripts/auto_detect_rtp.sh

# ターミナル2: 通話を開始
# 自動的にRTPポート情報が取得されます
```

### ケース3: tcpdumpでRTPパケットを確認

```bash
# 1. RTPポートを取得
/opt/libertycall/scripts/detect_rtp_port.sh

# 2. 出力されたtcpdumpコマンドを実行
sudo tcpdump -n -i any udp port 7182 -vvv -c 20
```

---

## トラブルシューティング

### Event Socketに接続できない場合

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

