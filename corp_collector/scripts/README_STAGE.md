# ステージ管理機能

メール送信のステージ管理機能です。誤送信を防ぎ、各顧客がどのメールを受け取ったかを追跡できます。

## ステージ一覧

| ステージ | 説明 | 次のステージ |
|---------|------|------------|
| `initial` | 初回メール送信前 | `follow1` |
| `follow1` | フォローメール1送信済み | `follow2` |
| `follow2` | フォローメール2送信済み | `follow3` |
| `follow3` | フォローメール3送信済み | `completed` |
| `completed` | すべてのフォローメール送信完了 | なし |

## CSVファイルの構造

`master_leads.csv`には以下の列があります：

```csv
email,company_name,address,stage
t-yano@serio-k.co.jp,セリオ建設株式会社,〒540-0012 大阪市中央区谷町1丁目3番27号 大手前建設会館内,initial
info@hr-symphony.co.jp,株式会社 HRシンフォニー,〒533-0033 大阪府大阪市東淀川区東中島1-6-14 新大阪第2日大ビル8F,initial
```

## 使用方法

### 1. 現在のステージを確認

```bash
cd /opt/libertycall/corp_collector
python3 scripts/update_stage.py user@example.com
```

### 2. ステージを次のステージに進める

```bash
python3 scripts/update_stage.py user@example.com --next
```

### 3. 特定のステージに設定

```bash
python3 scripts/update_stage.py user@example.com --stage follow1
```

### 4. ステージ一覧を表示

```bash
python3 scripts/update_stage.py --list
```

## Pythonコードでの使用例

### ステージ更新

```python
from pathlib import Path
from src.stage_manager import StageManager

# ステージマネージャーの初期化
manager = StageManager(Path("data/output/master_leads.csv"))

# ステージを次のステージに進める
new_stage = manager.update_stage_to_next("user@example.com")
if new_stage:
    print(f"ステージ更新: {new_stage}")

# 特定のステージに設定
manager.update_stage("user@example.com", "follow1")
```

### ステージごとのレシピエント取得

```python
# initialステージのレシピエントを取得
recipients = manager.get_recipients_by_stage("initial")
for recipient in recipients:
    print(f"{recipient['email']}: {recipient['company_name']}")
```

### 便利関数の使用

```python
from src.stage_manager import update_stage, update_stage_to_next

# ステージを更新
update_stage("user@example.com", "follow1")

# 次のステージに進める
new_stage = update_stage_to_next("user@example.com")
```

## メール送信システムとの連携

メール送信後、ステージを更新する例：

```python
from src.stage_manager import StageManager
from pathlib import Path

manager = StageManager(Path("data/output/master_leads.csv"))

def send_email(recipient_email: str, stage: str):
    """メール送信とステージ更新"""
    # メール送信処理
    # ...
    
    # 送信成功後、ステージを更新
    if stage == "initial":
        manager.update_stage(recipient_email, "follow1")
    elif stage == "follow1":
        manager.update_stage(recipient_email, "follow2")
    elif stage == "follow2":
        manager.update_stage(recipient_email, "follow3")
    elif stage == "follow3":
        manager.update_stage(recipient_email, "completed")
    
    # または、次のステージに進める
    manager.update_stage_to_next(recipient_email)
```

## 送信ロジックの例

```python
from src.stage_manager import StageManager
from pathlib import Path

manager = StageManager(Path("data/output/master_leads.csv"))

def send_emails():
    """ステージに応じたメール送信"""
    # 各ステージのレシピエントを取得
    initial_recipients = manager.get_recipients_by_stage("initial")
    follow1_recipients = manager.get_recipients_by_stage("follow1")
    follow2_recipients = manager.get_recipients_by_stage("follow2")
    follow3_recipients = manager.get_recipients_by_stage("follow3")
    
    # 初回メール送信
    for recipient in initial_recipients:
        send_initial_email(recipient)
        manager.update_stage_to_next(recipient["email"])
    
    # フォローメール1送信
    for recipient in follow1_recipients:
        send_follow1_email(recipient)
        manager.update_stage_to_next(recipient["email"])
    
    # フォローメール2送信
    for recipient in follow2_recipients:
        send_follow2_email(recipient)
        manager.update_stage_to_next(recipient["email"])
    
    # フォローメール3送信
    for recipient in follow3_recipients:
        send_follow3_email(recipient)
        manager.update_stage_to_next(recipient["email"])
```

## 注意事項

- ステージは大文字小文字を区別します（`initial`, `follow1`, `follow2`, `follow3`, `completed`）
- メールアドレスの比較は大文字小文字を区別しません
- `completed`ステージのレシピエントには、それ以上メールを送信しないでください
- ステージ更新は即座にCSVファイルに反映されます（バックアップは作成されません）

## トラブルシューティング

### ステージが更新されない

1. メールアドレスが正しいか確認
2. マスターファイルに該当のメールアドレスが存在するか確認
3. マスターファイルに`stage`列が存在するか確認

### CSVファイルが壊れた

バックアップファイル（`master_leads.csv.backup`）から復元できます：

```bash
cd /opt/libertycall/corp_collector
cp data/output/master_leads.csv.backup data/output/master_leads.csv
```

