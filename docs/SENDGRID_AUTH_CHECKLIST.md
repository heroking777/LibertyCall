# SendGrid 送信ドメイン認証チェックシート

> **目的**: SPF / DKIM / DMARC の3点セットを確実に設定し、配信到達率を最大化する

**最終更新**: 2025-12-19  
**対象ドメイン**: `_________________` (例: example.com)

---

## 📋 チェックリスト概要

| 項目 | ステータス | 確認日 | 備考 |
|------|-----------|--------|------|
| **① SPF** | ⬜ 未確認 / ✅ 合格 / ❌ 要修正 | YYYY-MM-DD | |
| **② DKIM** | ⬜ 未確認 / ✅ 合格 / ❌ 要修正 | YYYY-MM-DD | |
| **③ DMARC** | ⬜ 未確認 / ✅ 合格 / ❌ 要修正 | YYYY-MM-DD | |
| **SendGrid認証** | ⬜ 未確認 / ✅ Authenticated / ❌ Unverified | YYYY-MM-DD | |

---

## ① SPF（Sender Policy Framework）

### 目的
送信ドメインがSendGrid経由で送信されていることを受信サーバーに証明する

### 確認方法

#### 1. DNSレコード確認
**ホスト名**: `@` または ルートドメイン（例: `example.com`）  
**レコードタイプ**: `TXT`

**期待される値**:
```
v=spf1 include:sendgrid.net ~all
```

**既存のSPFがある場合（Google Workspaceなど）**:
```
v=spf1 include:_spf.google.com include:sendgrid.net ~all
```

#### 2. 現在の設定値
```
_________________________________________________________
_________________________________________________________
```

#### 3. 確認ツール
- **MXToolbox SPF Checker**: https://mxtoolbox.com/spf.aspx
- **SPF Record Checker**: https://www.spf-record.com/

#### 4. 確認結果
- ⬜ **未確認**
- ✅ **PASS** - 「SPF record published」「PASS」と表示
- ❌ **FAIL** - レコードが見つからない、または `include:sendgrid.net` が含まれていない

#### 5. 修正が必要な場合
1. DNS管理画面（Cloudflare / Xserver / Route53など）にログイン
2. ルートドメイン（`@`）のTXTレコードを追加/編集
3. 上記のSPFレコードを設定
4. **反映待ち**: 最大24〜48時間（通常は数分〜数時間）

---

## ② DKIM（DomainKeys Identified Mail）

### 目的
送信メールに署名を付与し、改ざんされていないことを証明する（**SendGrid認証で最重要**）

### 確認方法

#### 1. SendGridダッシュボード確認
1. SendGridにログイン: https://app.sendgrid.com/
2. 左メニュー → **Settings** → **Sender Authentication**
3. **Authenticate Your Domain** をクリック
4. 対象ドメインを選択
5. **Verified** と表示されていればOK

#### 2. DNSレコード確認
SendGridから提供される2つのCNAMEレコードをDNSに設定する必要があります。

**レコード1**:
- **ホスト名**: `s1._domainkey` (例: `s1._domainkey.example.com`)
- **レコードタイプ**: `CNAME`
- **値**: `s1.domainkey.u[API_KEY].wl.sendgrid.net`
  - ※ `[API_KEY]` はSendGridから提供される固有の値

**レコード2**:
- **ホスト名**: `s2._domainkey` (例: `s2._domainkey.example.com`)
- **レコードタイプ**: `CNAME`
- **値**: `s2.domainkey.u[API_KEY].wl.sendgrid.net`

#### 3. 現在の設定値
**s1._domainkey**:
```
ホスト名: s1._domainkey._________________
CNAME: _________________________________________________________
```

**s2._domainkey**:
```
ホスト名: s2._domainkey._________________
CNAME: _________________________________________________________
```

#### 4. 確認ツール
- **DKIM Validator**: https://dkimvalidator.com/
- **SendGrid Sender Authentication**: https://app.sendgrid.com/settings/sender_auth

#### 5. 確認結果
- ⬜ **未確認**
- ✅ **Verified** - SendGridダッシュボードで緑マーク「Authenticated」
- ❌ **Unverified** - 黄色/赤マーク、DNS反映待ちまたは設定ミス

#### 6. テスト送信確認
テストメールを送信し、受信メールのヘッダーを確認:
```
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=example.com; ...
Authentication-Results: ... dkim=pass ...
```

#### 7. 修正が必要な場合
1. SendGridダッシュボードで「Authenticate Your Domain」を実行
2. 表示されるCNAMEレコードをDNSに追加
3. **反映待ち**: 最大24〜48時間（通常は数分〜数時間）
4. SendGridダッシュボードで「Verify」をクリック

---

## ③ DMARC（Domain-based Message Authentication, Reporting, and Conformance）

### 目的
SPF/DKIMの認証結果に基づき、受信サーバーがメールをどう扱うかを指示するポリシー

### 確認方法

#### 1. DNSレコード確認
**ホスト名**: `_dmarc` (例: `_dmarc.example.com`)  
**レコードタイプ**: `TXT`

**初回設定（安全策）**:
```
v=DMARC1; p=none; rua=mailto:dmarc@example.com
```

**段階的強化（SPF/DKIMが安定してから）**:
```
v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com; ruf=mailto:dmarc@example.com
```

**最終形（本番環境推奨）**:
```
v=DMARC1; p=reject; rua=mailto:dmarc@example.com; ruf=mailto:dmarc@example.com; sp=reject; aspf=r; adkim=r
```

**パラメータ説明**:
- `p=none` - 何もしない（レポート収集のみ）
- `p=quarantine` - 迷惑フォルダに振り分け
- `p=reject` - メールを拒否
- `rua` - 集約レポート送信先メールアドレス
- `ruf` - 失敗レポート送信先メールアドレス

#### 2. 現在の設定値
```
ホスト名: _dmarc._________________
TXT: _________________________________________________________
_________________________________________________________
```

#### 3. 確認ツール
- **MXToolbox DMARC Checker**: https://mxtoolbox.com/dmarc.aspx
- **DMARC Analyzer**: https://www.dmarcanalyzer.com/

#### 4. 確認結果
- ⬜ **未確認**
- ✅ **PASS** - DMARCレコードが存在し、正しい形式
- ❌ **FAIL** - レコードが見つからない、または形式が不正

#### 5. 修正が必要な場合
1. DNS管理画面にログイン
2. `_dmarc` のTXTレコードを追加/編集
3. まずは `p=none` で設定（安全策）
4. **反映待ち**: 最大24〜48時間
5. レポートを確認し、問題がなければ段階的に `p=quarantine` → `p=reject` に強化

---

## 📊 SendGridダッシュボード全体確認

### 確認手順
1. SendGridにログイン: https://app.sendgrid.com/
2. 左メニュー → **Settings** → **Sender Authentication**
3. **Authenticated Domain** 欄を確認

### ステータス
- ✅ **緑マーク「Authenticated」** - すべて正常
- ⚠️ **黄色「Partially Verified」** - 一部未設定
- ❌ **赤マーク「Unverified」** - DNS反映待ちまたは設定ミス

### 現在の状態
```
ステータス: ⬜ Authenticated / ⬜ Partially Verified / ⬜ Unverified
確認日時: YYYY-MM-DD HH:MM
```

---

## 🔍 確認ツール一覧

| ツール名 | URL | 用途 |
|---------|-----|------|
| **MXToolbox SPF Checker** | https://mxtoolbox.com/spf.aspx | SPFレコード確認 |
| **MXToolbox DMARC Checker** | https://mxtoolbox.com/dmarc.aspx | DMARCレコード確認 |
| **DKIM Validator** | https://dkimvalidator.com/ | DKIM署名検証 |
| **SPF Record Checker** | https://www.spf-record.com/ | SPFレコード詳細確認 |
| **DMARC Analyzer** | https://www.dmarcanalyzer.com/ | DMARCレポート分析 |
| **SendGrid Sender Auth** | https://app.sendgrid.com/settings/sender_auth | SendGrid認証状態確認 |

---

## 📝 DNSレコード記録テンプレート

### 使用しているDNSプロバイダ
```
⬜ Cloudflare
⬜ Xserver
⬜ Route53 (AWS)
⬜ その他: _________________
```

### 設定済みレコード一覧

#### SPF
```
ホスト名: @
タイプ: TXT
値: v=spf1 include:sendgrid.net ~all
設定日: YYYY-MM-DD
```

#### DKIM
```
ホスト名: s1._domainkey
タイプ: CNAME
値: s1.domainkey.u[API_KEY].wl.sendgrid.net
設定日: YYYY-MM-DD

ホスト名: s2._domainkey
タイプ: CNAME
値: s2.domainkey.u[API_KEY].wl.sendgrid.net
設定日: YYYY-MM-DD
```

#### DMARC
```
ホスト名: _dmarc
タイプ: TXT
値: v=DMARC1; p=none; rua=mailto:dmarc@example.com
設定日: YYYY-MM-DD
```

---

## ✅ 最終確認チェックリスト

- [ ] SPFレコードが正しく設定され、MXToolboxで「PASS」と表示される
- [ ] DKIMの2つのCNAMEレコードがDNSに設定されている
- [ ] SendGridダッシュボードで「Authenticated」と表示される
- [ ] DMARCレコードが設定されている（最低限 `p=none`）
- [ ] テスト送信でメールヘッダーに `dkim=pass` が含まれる
- [ ] 迷惑フォルダに入らず、受信トレイに届くことを確認

---

## 🚨 よくある問題と対処法

### 問題1: SPFが「FAIL」と表示される
**原因**: `include:sendgrid.net` が含まれていない、またはSPFレコード自体が存在しない  
**対処**: DNSにSPFレコードを追加/修正

### 問題2: DKIMが「Unverified」のまま
**原因**: DNS反映待ち、またはCNAMEレコードの設定ミス  
**対処**: 
1. DNS設定を再確認（タイポ、ホスト名の誤りなど）
2. 最大48時間待つ
3. SendGridダッシュボードで「Verify」を再実行

### 問題3: DMARCレポートが届かない
**原因**: `rua` のメールアドレスが正しく設定されていない  
**対処**: DNSレコードの `rua=mailto:` の値を確認

### 問題4: メールが迷惑フォルダに入る
**原因**: SPF/DKIM/DMARCのいずれかが未設定、またはIP Reputationが低い  
**対処**: 
1. 上記3点セットをすべて設定
2. SendGridのIP Reputationを確認（Settings → IP Addresses）
3. 段階的に送信量を増やす

---

## 📅 定期確認スケジュール

| 確認項目 | 頻度 | 次回確認日 |
|---------|------|-----------|
| SPF/DKIM/DMARC設定 | 月1回 | YYYY-MM-DD |
| SendGrid認証状態 | 月1回 | YYYY-MM-DD |
| 配信到達率 | 週1回 | YYYY-MM-DD |
| 迷惑フォルダ率 | 週1回 | YYYY-MM-DD |

---

## 📌 メモ欄

```
_________________________________________________________
_________________________________________________________
_________________________________________________________
_________________________________________________________
```

---

**作成日**: 2025-12-19  
**次回確認予定**: YYYY-MM-DD

