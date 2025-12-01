# データベース設定とAlembic使用方法

## 概要

LibertyCallプロジェクトでは、SQLiteデータベースを使用して通話情報とログを管理しています。
データベーススキーマの管理にはAlembicを使用しています。

## データベース構成

### データベースファイル

- **パス**: `/opt/libertycall/call_console.db`
- **タイプ**: SQLite 3
- **エンコーディング**: UTF-8

### テーブル構造

#### `calls` テーブル
通話情報を格納します。

| カラム名 | 型 | 説明 |
|---------|-----|------|
| id | INTEGER | 主キー |
| call_id | VARCHAR(64) | 通話ID（ユニーク） |
| client_id | VARCHAR(128) | クライアントID |
| started_at | DATETIME | 通話開始時刻 |
| ended_at | DATETIME | 通話終了時刻（NULL可） |
| current_state | VARCHAR(64) | 現在の状態 |
| is_transferred | BOOLEAN | 転送フラグ |
| handover_summary | TEXT | 転送サマリー（NULL可） |

#### `call_logs` テーブル
通話ログを格納します。

| カラム名 | 型 | 説明 |
|---------|-----|------|
| id | INTEGER | 主キー |
| call_id | VARCHAR(64) | 通話ID（外部キー） |
| timestamp | DATETIME | ログ時刻 |
| role | VARCHAR(16) | ロール（'user' または 'ai'） |
| text | TEXT | ログテキスト |
| state | VARCHAR(64) | 状態 |

#### `alembic_version` テーブル
Alembicのマイグレーション管理用テーブル。

| カラム名 | 型 | 説明 |
|---------|-----|------|
| version_num | VARCHAR(32) | マイグレーションバージョン |

## 環境変数設定

`.env`ファイルに以下の設定を追加してください：

```bash
# Database Configuration
# SQLite database path (relative to project root)
DATABASE_URL=sqlite:///call_console.db

# Database echo (for debugging SQL queries)
DB_ECHO=false
```

### 設定の説明

- **DATABASE_URL**: データベース接続URL
  - SQLiteの場合: `sqlite:///call_console.db`（相対パス）または `sqlite:////absolute/path/to/db.db`（絶対パス）
  - 相対パスの場合、プロジェクトルートからの相対パスとして解釈されます
- **DB_ECHO**: SQLクエリをログに出力するかどうか（デバッグ用）
  - `true`: SQLクエリをログに出力
  - `false`: 出力しない（推奨）

## Alembic使用方法

### 初期設定

Alembicは既に設定済みです。以下のファイルが存在します：

- `alembic.ini`: Alembic設定ファイル
- `alembic/env.py`: 環境設定
- `alembic/versions/`: マイグレーションファイル格納ディレクトリ

### 現在のバージョン確認

```bash
cd /opt/libertycall
/opt/libertycall/venv/bin/alembic current
```

出力例：
```
20251121_01 (head)
```

### マイグレーション履歴確認

```bash
/opt/libertycall/venv/bin/alembic history
```

### 新しいマイグレーション作成

モデルを変更した後、新しいマイグレーションを作成します：

```bash
# 自動検出でマイグレーション作成
/opt/libertycall/venv/bin/alembic revision --autogenerate -m "説明"

# 手動でマイグレーション作成
/opt/libertycall/venv/bin/alembic revision -m "説明"
```

### マイグレーション適用

```bash
# 最新バージョンにアップグレード
/opt/libertycall/venv/bin/alembic upgrade head

# 特定のバージョンにアップグレード
/opt/libertycall/venv/bin/alembic upgrade <revision>

# 1つ前のバージョンにダウングレード
/opt/libertycall/venv/bin/alembic downgrade -1

# 特定のバージョンにダウングレード
/opt/libertycall/venv/bin/alembic downgrade <revision>
```

### マイグレーションファイルの構造

マイグレーションファイルは `alembic/versions/` ディレクトリに保存されます。

例: `alembic/versions/20251121_01.py`

```python
"""Initial migration

Revision ID: 20251121_01
Revises: 
Create Date: 2025-11-21 08:18:22.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '20251121_01'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # アップグレード時の処理
    pass

def downgrade() -> None:
    # ダウングレード時の処理
    pass
```

## データベース接続の使用

### console_backendモジュール経由

```python
from console_backend.service_client import (
    start_call,
    append_call_log,
    complete_call,
    mark_transfer,
)

# 通話開始
start_call("call-123", "client-001", state="init")

# ログ追加
append_call_log(
    "call-123",
    role="user",
    text="こんにちは",
    state="greeting"
)

# 通話完了
complete_call("call-123")
```

### 直接SQLAlchemyを使用

```python
from console_backend.database import SessionLocal
from console_backend.models import Call, CallLog

with SessionLocal() as db:
    # 通話を取得
    call = db.query(Call).filter(Call.call_id == "call-123").first()
    
    # ログを取得
    logs = db.query(CallLog).filter(CallLog.call_id == "call-123").all()
```

## トラブルシューティング

### データベース接続エラー

1. `.env`ファイルの`DATABASE_URL`を確認
2. データベースファイルのパーミッションを確認
3. データベースファイルが存在するか確認

```bash
ls -l /opt/libertycall/call_console.db
```

### Alembicエラー

1. `alembic.ini`の設定を確認
2. `alembic/env.py`が正しく設定されているか確認
3. データベースの`alembic_version`テーブルを確認

```bash
sqlite3 /opt/libertycall/call_console.db "SELECT * FROM alembic_version;"
```

### マイグレーション競合

複数の開発者が同時にマイグレーションを作成した場合、競合が発生する可能性があります。

解決方法：
1. 最新のマイグレーションを取得
2. 競合を解決
3. 新しいマイグレーションを作成

## 参考資料

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

