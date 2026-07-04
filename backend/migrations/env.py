"""
Flask-Migrate / Alembic 迁移环境配置

由 flask db init 初始化后自动生成。
此文件配置 Alembic 如何连接到应用和数据库。
"""
import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger('alembic.env')


def get_engine():
    return current_app.extensions['migrate'].engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace('%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# 配置数据库连接 URL
config.set_main_option('sqlalchemy.url', get_engine_url())

# 导入所有模型以便 Alembic 自动检测变更
from app import db
from app.models import (
    Stock, Signal, Holding,
    TechnicalIndicator, Watchlist, UserMemory,
    Portfolio, PortfolioHolding, PaperTrade,
    Alert, Drawing,
    ConditionRegistry,
    SystemConfig, SyncLog
)
target_metadata = db.metadata


def run_migrations_offline():
    """离线模式运行迁移（仅生成 SQL 脚本，不连接数据库）"""
    url = config.get_main_option('sqlalchemy.url')
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """在线模式运行迁移（连接数据库执行迁移）"""
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,     # 检测列类型变更
            compare_server_default=True,  # 检测默认值变更
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
