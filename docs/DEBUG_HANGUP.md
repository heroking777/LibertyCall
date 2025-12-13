# AUTO-HANGUP デバッグ手順

## 問題の状況

- ✅ 無音検知は成功（`[SILENCE DETECTED]` が出ている）
- ✅ hangup要求発行までは成功（`RUN_CMD: asterisk -rx channel request hangup` が出ている）
- ❓ 実際の切断成立は未確認

## 次回通話時に確認すべきコマンド

### 1. 通話中のチャネル一覧を確認

```bash
asterisk -rx "core show channels verbose"
```

**確認ポイント:**
- `PJSIP/trunk-rakuten-in-XXXXX` 以外に
- `UnicastRTP/...`
- `Local/...`
- `PJSIP/...` のもう片側
が同時に出ているか

**出ていたら:** 切るべきチャネルを間違えている可能性が高い

### 2. Asteriskのログでhangup実行を確認

```bash
tail -n 200 /var/log/asterisk/full.log | grep -E "00000058|Hangup|requested hangup|UnicastRTP|PJSIP/"
```

**確認ポイント:**
- `hangup` 原因が `app_hangup` / `Soft Hangup Request` 的なのが出ているか
- それとも `BYE` / `CANCEL` / `normal clearing` 系（相手側切断）が出ているか

**Auto-hangupが効いたなら:** `app_hangup` / `Soft Hangup Request` が出る
**あなたが切ったなら:** `BYE` / `CANCEL` / `normal clearing` 系が出る

### 3. Gatewayログでhangup要求を確認

```bash
grep -E "AUTO-HANGUP|SILENCE DETECTED" /opt/libertycall/logs/systemd_gateway_stdout.log | tail -10
```

### 4. hangup_call.pyの実行結果を確認

```bash
tail -n 20 /opt/libertycall/logs/hangup_call.log
```

**確認ポイント:**
- `RUN_CMD_RESULT` に何が返ってきているか
- `HANGUP_RESULT` に何が返ってきているか

## よくある問題パターン

### 1. そもそもhangupすべき"相手チャネル"じゃないものに投げている

ログに出ているのは `PJSIP/trunk-rakuten-in-00000058` だけど、実際に聞いている音声のチャネルが別の legs / Local / UnicastRTP 側の可能性がある。

**対処:** `core show channels verbose` で全チャネルを確認し、正しいチャネルを切る

### 2. 既に通話が終了済み/状態が変わっていて、要求が空振りしている

要求は通ったが実際には対象がもう死んでいた。

**対処:** Asteriskログで `Hangup` イベントのタイムスタンプを確認

### 3. 自動hangupは動いているが"実害"はない（＝あなたが先に切った）

タイムスタンプ上、あなたが切った直後にAUTO-HANGUPが走っただけ。

**対処:** Asteriskログのタイムスタンプを比較

## 確認用スクリプト

次回通話時に以下を実行すると、必要な情報が一括で取得できます：

```bash
#!/bin/bash
echo "=== チャネル一覧 ==="
asterisk -rx "core show channels verbose"
echo ""
echo "=== Asteriskログ（直近200行） ==="
tail -n 200 /var/log/asterisk/full.log | grep -E "Hangup|requested hangup|UnicastRTP|PJSIP/"
echo ""
echo "=== Gatewayログ ==="
grep -E "AUTO-HANGUP|SILENCE DETECTED" /opt/libertycall/logs/systemd_gateway_stdout.log | tail -10
echo ""
echo "=== hangup_call.pyログ ==="
tail -n 20 /opt/libertycall/logs/hangup_call.log
```

## 次のステップ

1. 次回通話時に上記のコマンドを実行
2. 結果を確認して、どのパターンに該当するか特定
3. 該当パターンに応じた修正を実施

