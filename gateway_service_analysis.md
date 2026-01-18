# gateway.service 依存関係調査レポート

調査日時: 2025-01-XX

## 1. 検出ファイル一覧

### 存在するファイル
- ✅ `/etc/systemd/system/gateway.service` - **存在確認済み**

### 存在しないファイル
- ❌ `/lib/systemd/system/gateway.service` - 存在しない

---

## 2. gateway.service の詳細内容

### ファイル: `/etc/systemd/system/gateway.service`

```ini
[Unit]
Description=LibertyCall Realtime Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/libertycall
ExecStart=/opt/libertycall/venv/bin/python3 /opt/libertycall/gateway/realtime_gateway.py
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"
Environment="PATH=/opt/libertycall/venv/bin:/usr/bin:/bin"
Environment="LC_ASR_PROVIDER=google"
Environment="LC_ASR_STREAMING_ENABLED=1"
Environment="LC_RTP_PORT=7002"
StandardOutput=append:/opt/libertycall/logs/gateway_stdout.log
StandardError=append:/opt/libertycall/logs/gateway_stderr.log

[Install]
WantedBy=multi-user.target
```

### 重要なセクション分析

#### [Unit] セクション
- **After**: `network.target` のみ（他のサービスへの依存なし）
- **Wants**: なし
- **Requires**: なし
- **PartOf**: なし
- **Alias**: なし

#### [Service] セクション
- **ExecStart**: `/opt/libertycall/venv/bin/python3 /opt/libertycall/gateway/realtime_gateway.py`
- **User**: root
- **Restart**: always（自動再起動有効）

#### [Install] セクション
- **WantedBy**: `multi-user.target`（標準的な設定）

---

## 3. 依存関係調査結果

### 3.1 gateway.service が依存しているサービス
- **network.target** のみ（標準的なネットワーク依存）

### 3.2 gateway.service に依存しているサービス（Reverse dependency）
- **検出されず**（他のサービスから gateway.service を参照している設定は見つかりませんでした）

### 3.3 他のサービスファイルでの gateway への言及
- **検出されず**（他の systemd サービスファイルで gateway.service を参照している設定は見つかりませんでした）

---

## 4. ⚠️ 重要な発見：重複実行の可能性

### 問題点
`gateway.service` と `service` の両方が **同じ `realtime_gateway.py` を実行** しています：

#### gateway.service
```ini
ExecStart=/opt/libertycall/venv/bin/python3 /opt/libertycall/gateway/realtime_gateway.py
```

#### service
```ini
ExecStart=/opt/libertycall/.venv/bin/python /opt/libertycall/gateway/realtime_gateway.py
```

### 影響
- **同じプロセスが2回起動される可能性**（ポート競合のリスク）
- **RTP ポート 7002 の重複使用**の可能性
- **リソースの無駄遣い**

### 推奨事項
- `gateway.service` を削除し、`service` のみを使用することを推奨
- または、`service` を削除し、`gateway.service` のみを使用することを推奨

---

## 5. 関連サービスとの連携確認

### 5.1 service との関係
- ❌ **直接的な依存関係なし**（Wants, Requires, After, PartOf など）
- ⚠️ **同じプロセスを実行**（重複実行の可能性）

### 5.2 asterisk との関係
- ❌ **依存関係なし**（gateway.service の設定に asterisk への言及なし）
- ℹ️ **機能的な連携はある**（Asterisk から RTP を受信するが、systemd レベルでの依存はなし）

### 5.3 voicecore との関係
- ❌ **依存関係なし**（voicecore サービスは検出されませんでした）

### 5.4 gateway.target との関係
- ❌ **依存関係なし**（gateway.target は検出されませんでした）

---

## 6. 安全性評価

### 評価基準
- **安全**: 削除しても他のサービス・プロセス・ソケットに影響なし
- **要注意**: 削除前に確認が必要な項目あり
- **危険**: 削除すると他のサービスが停止する可能性

### 評価結果: **要注意** ⚠️

### 理由

#### ✅ 安全な点
1. **他のサービスからの依存なし**
   - 他の systemd サービスが gateway.service に依存していない
   - Wants, Requires, PartOf などの設定がない

2. **標準的な設定**
   - WantedBy=multi-user.target のみ（標準的な設定）
   - 特別な Alias や連携設定がない

#### ⚠️ 要注意な点
1. **重複実行の可能性**
   - `service` が同じプロセスを実行している
   - 両方が有効な場合、ポート競合やリソース競合の可能性

2. **プロセス状態の確認が必要**
   - 現在 gateway.service で実行中のプロセスがあるか確認が必要
   - ポート 7002, 9001 の使用状況を確認が必要

3. **削除前の確認事項**
   - `service` が正常に動作しているか確認
   - ポート競合がないか確認
   - ログファイル（`/opt/libertycall/logs/gateway_*.log`）の確認

---

## 7. 削除前の推奨手順

### ステップ 1: 現在の状態確認
```bash
# gateway.service の状態確認
systemctl status gateway.service

# service の状態確認
systemctl status service

# 実行中のプロセス確認
ps aux | grep realtime_gateway

# ポート使用状況確認
sudo ss -tlnp | grep -E "(7002|9001)"
```

### ステップ 2: gateway.service を無効化（削除前のテスト）
```bash
sudo systemctl stop gateway.service
sudo systemctl disable gateway.service
```

### ステップ 3: service が正常に動作するか確認
```bash
sudo systemctl start service
sudo systemctl status service
```

### ステップ 4: 問題がなければ削除
```bash
sudo rm /etc/systemd/system/gateway.service
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

---

## 8. 最終判定

### 判定: **削除可能（要注意事項あり）** ✅⚠️

### 理由
1. ✅ **他のサービスへの影響なし**: 他の systemd サービスが gateway.service に依存していない
2. ⚠️ **重複実行の解消**: `service` が同じプロセスを実行しているため、gateway.service は不要の可能性が高い
3. ⚠️ **削除前の確認必須**: 削除前に `service` が正常に動作することを確認する必要がある

### 推奨アクション
1. **削除前に `service` が正常に動作することを確認**
2. **ポート競合がないことを確認**
3. **削除後も `service` が正常に動作することを確認**

---

## 9. 補足情報

### プロジェクトドキュメントでの言及
- `docs/project_tree.txt` では Gateway は重要なコンポーネントとして記載されているが、`gateway.service` への直接的な言及はなし
- Gateway は RTP ポート 7002 と WebSocket ポート 9001 を使用

### 開発スクリプトでの言及
- `scripts/dev_run_gateway.sh` では `service` を停止してから開発用に gateway を起動している
- これは `service` と gateway が同じプロセスを実行していることを示唆

---

## 10. 結論

`gateway.service` は削除可能ですが、以下の点に注意が必要です：

1. **削除前に `service` が正常に動作することを確認**
2. **ポート競合がないことを確認**
3. **削除後もシステムが正常に動作することを確認**

削除することで、重複実行の問題が解消され、システムがよりシンプルになります。
