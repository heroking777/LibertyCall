# 本リストへの追記機能

`master_leads.csv`を本リスト（マスターファイル）として、毎日新しいデータを追記する機能です。

## 機能

- 本リストに新しいCSVファイルのデータを追記
- メールアドレスで重複チェック（既存のメールアドレスはスキップ）
- 同じファイル内の重複も自動除外

## 使用方法

### 1. 日付を指定して追記

```bash
cd /opt/libertycall/corp_collector
python3 scripts/append_to_master.py --date 20251205
```

### 2. ファイルパスを指定して追記

```bash
python3 scripts/append_to_master.py data/output/leads_20251205.csv
```

### 3. 今日の日付のファイルを自動検出して追記

```bash
python3 scripts/append_to_master.py
```

### 4. シェルスクリプトで実行

```bash
./scripts/append_daily.sh
```

## 本リストファイルの変更

デフォルトでは `data/output/master_leads.csv` が本リストとして使用されます。
別のファイルを本リストにしたい場合は `--master` オプションを使用してください。

```bash
python3 scripts/append_to_master.py --master data/output/master_leads.csv --date 20251205
```

## 毎日自動実行（cron設定例）

```bash
# 毎日午前2時に実行
0 2 * * * cd /opt/libertycall/corp_collector && /usr/bin/python3 scripts/append_to_master.py >> /var/log/append_master.log 2>&1
```

または、シェルスクリプトを使用：

```bash
0 2 * * * /opt/libertycall/corp_collector/scripts/append_daily.sh >> /var/log/append_master.log 2>&1
```

## 処理内容

1. 本リストから既存のメールアドレスを読み込み
2. 新しいCSVファイルからレコードを読み込み
3. メールアドレスで重複チェック
4. 新規レコードのみを本リストに追記

## 注意事項

- 本リストファイルは上書きされません（追記のみ）
- メールアドレスが空のレコードは追記されません
- メールアドレスの大文字小文字は区別しません（重複チェック時）

