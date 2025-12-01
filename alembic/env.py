"""Alembic環境設定."""

from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# この設定オブジェクトは Alembic Config オブジェクトで、
# Alembic.ini ファイルから読み込まれます。
config = context.config

# .envファイルからデータベースURLを読み込む
from console_backend.config import get_settings
settings = get_settings()

# alembic.iniのsqlalchemy.urlを上書き
config.set_main_option("sqlalchemy.url", settings.database_url)

# ログ設定を解釈する
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# メタデータオブジェクトをターゲットに追加
from console_backend.models import Base
target_metadata = Base.metadata

# その他の値は alembic.ini で定義されています
# 例: target_metadata, compare_type, compare_server_default など


def run_migrations_offline() -> None:
    """'offline' モードでマイグレーションを実行.

    これは、SQLAlchemy URL を設定し、Engine を作成せずに
    context.execute() を使用して SQL スクリプトを生成するように設定します。

    呼び出し元のコンテキストで接続を提供する必要があります。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """'online' モードでマイグレーションを実行.

    この場合、Engine を作成し、接続をコンテキストに関連付けます。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

