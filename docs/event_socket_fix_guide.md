# FreeSWITCH Event Socket 接続エラー解決ガイド

## エラーの意味

`[ERROR] fs_cli.c:1699 main() Error Connecting []`

このエラーは、fs_cliがFreeSWITCHのEvent Socketに接続できていない状態を示します。

FreeSWITCHプロセスは動いているように見えても、Event Socketが接続を受け付けていない可能性があります。

---

## よくある接続NGの原因

### 1. Event SocketがIPv6だけでbindされている

**問題:**
- FreeSWITCHのデフォルト設定では`listen-ip`が`::`（IPv6）になっている
- IPv4-onlyのVPSでは接続できない

**解決方法:**
- `listen-ip`を`0.0.0.0`または`127.0.0.1`に設定

### 2. Event Socketの設定ファイルにACLが入っていて拒否されている

**問題:**
- ACLによってIPv4のローカルIPが許可されていない

**解決方法:**
- `apply-inbound-acl`をコメントアウト、または`loopback.auto`に設定

### 3. FreeSWITCHの起動順でEvent Socketのbindが失敗している

**問題:**
- ログ上は起動完了していても、実際にはソケットが開けていない

**解決方法:**
- systemdの`network-online.target`を待つ設定を追加（既に実施済み）

---

## 絶対やるべき設定

### 設定①: Event Socketのlisten-ipを修正

**ファイル:** `/usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml`

```xml
<configuration name="event_socket.conf" description="Socket Client">
  <settings>
    <param name="nat-map" value="false"/>
    <param name="listen-ip" value="0.0.0.0"/>
    <param name="listen-port" value="8021"/>
    <param name="password" value="ClueCon"/>
    <!--<param name="apply-inbound-acl" value="loopback.auto"/>-->
    <!--<param name="stop-on-bind-error" value="true"/>-->
  </settings>
</configuration>
```

**重要ポイント:**
- `listen-ip`を`0.0.0.0`に設定（IPv4で確実にlisten）
- `apply-inbound-acl`はコメントアウト（ACL制限を無効化）

**適用方法:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart freeswitch
```

### 設定②: ACLを確認する（必要に応じて）

もし`apply-inbound-acl`を有効にする場合は、`loopback.auto`を使用：

```xml
<param name="apply-inbound-acl" value="loopback.auto"/>
```

または、ACLファイルで`127.0.0.1/32`を許可：

```xml
<node type="allow" cidr="127.0.0.1/32"/>
```

---

## 接続テスト

### ワンライナーコマンド

```bash
# 再接続モードで接続テスト
fs_cli -H 127.0.0.1 -P 8021 -p ClueCon -r -x "status"
```

**成功時の出力例:**
```
UP 0 years, 0 days, 0 hours, 0 minutes, 47 seconds, ...
FreeSWITCH (Version 1.10.12-release ...) is ready
0 session(s) since startup
```

### 確認スクリプト

```bash
# 包括的な接続確認
/opt/libertycall/scripts/check_event_socket.sh
```

---

## 即効チェックコマンド

### 1. ポート8021のLISTEN状態確認

```bash
sudo netstat -tulnp | grep 8021
```

**期待される出力:**
```
tcp  0  0 0.0.0.0:8021  0.0.0.0:*  LISTEN  <PID>/freeswitch
```

### 2. Event Socket設定確認

```bash
cat /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml | grep -E "listen-ip|listen-port|password"
```

**期待される出力:**
```
    <param name="listen-ip" value="0.0.0.0"/>
    <param name="listen-port" value="8021"/>
    <param name="password" value="ClueCon"/>
```

### 3. FreeSWITCHプロセス確認

```bash
ps aux | grep freeswitch | grep -v grep
```

### 4. Event Socket起動ログ確認

```bash
sudo tail -100 /usr/local/freeswitch/log/freeswitch.log | grep "Socket up listening"
```

**期待される出力:**
```
2025-12-17 15:39:18.879912 100.00% [DEBUG] mod_event_socket.c:2982 Socket up listening on 0.0.0.0:8021
```

---

## 重要ポイントまとめ

✅ **Event SocketはIPv4でbindされないとfs_cliは繋がらない**
- `listen-ip`を`0.0.0.0`にするだけでよく繋がる

✅ **ACLにローカルIPを許可しないと接続NGになることもある**
- `apply-inbound-acl`をコメントアウト、または`loopback.auto`に設定

✅ **接続の成否は`fs_cli -r -x "status"`で確認**
- これでステータスが返ってくれば接続成功

✅ **ポート8021が`0.0.0.0:8021`でLISTENしていることを確認**
- `sudo netstat -tulnp | grep 8021`で確認

---

## トラブルシューティング

### 接続できない場合の確認手順

1. **FreeSWITCHが起動しているか確認**
   ```bash
   sudo systemctl status freeswitch
   ```

2. **ポート8021がLISTENしているか確認**
   ```bash
   sudo netstat -tulnp | grep 8021
   ```

3. **Event Socket設定を確認**
   ```bash
   cat /usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml
   ```

4. **FreeSWITCHを再起動**
   ```bash
   sudo systemctl restart freeswitch
   sleep 5
   fs_cli -H 127.0.0.1 -P 8021 -p ClueCon -r -x "status"
   ```

---

## 関連ファイル

- `/usr/local/freeswitch/conf/autoload_configs/event_socket.conf.xml` - Event Socket設定
- `/etc/systemd/system/freeswitch.service.d/override.conf` - systemd設定（network-online.target待機）
- `/opt/libertycall/scripts/check_event_socket.sh` - 接続確認スクリプト

