"""
SQLite → PostgreSQL 数据迁移脚本
==================================
将现有 SQLite 数据库中的所有业务表迁移到 PostgreSQL。
DuckDB 数据不动。

使用方法：
    cd backend
    python scripts/migrate_sqlite_to_pg.py

注意：
    - 执行前确保 PostgreSQL 已创建 stock_analysis 数据库
    - 执行前确保 Flask 已配置 DATABASE_URL=postgresql:///stock_analysis
    - 幂等设计：已存在的记录跳过（ON CONFLICT DO NOTHING）
"""

import os
import sys
from datetime import datetime

# 设置环境变量（确保使用 SQLite 连接读取）
os.environ['FLASK_ENV'] = 'development'

# 解析参数：--dry-run 预览不执行
DRY_RUN = '--dry-run' in sys.argv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app, db
from app.config import Config
from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('migrate')

# 迁移表顺序（按依赖关系，确保外键约束满足）
# 从 instance/test.db 的实际表名查询获得
TABLE_ORDER = [
    'stocks',           # 基础股票档案
    'daily_data',       # 日线行情
    'signals',          # 信号
    'holdings',         # 持仓
    'technical_indicators',  # 技术指标
    'watchlist',        # 自选股
    'user_memory',       # 用户记忆
    'portfolio',         # 投资组合
    'account_trades',    # 交易记录
    'account_snapshots', # 账户快照
    'alerts',            # 告警
    'drawings',          # 绘图
    'condition_registry',# 条件注册
    'system_config',     # 系统配置
    'sync_log',          # 同步日志
    'review_units',      # 复盘单元
    'playback_accounts', # 复盘账户
    'review_configs',    # 复盘配置
    'strategy_outputs',  # 策略输出
    'strategy_templates_v2', # 策略模板
    'portfolio_holdings',    # 组合持仓
    'paper_trades',      # 模拟交易
    'playback_reports',  # 复盘报告
    'account_cash_flow', # 账户现金流
    'notification_rules',    # 通知规则
    'notifications',     # 通知记录
    'notification_rule_stats', # 通知规则统计
    'report_archives',   # 报告归档
    'signal_records',    # 信号记录
    'virtual_positions', # 虚拟持仓
]


def main():
    """主迁移流程"""
    # 1. 创建 Flask 应用（使用 SQLite 读取）
    app_sqlite = create_app()

    with app_sqlite.app_context():
        # 2. 检查 PostgreSQL 是否可连接
        pg_url = os.environ.get('DATABASE_URL', 'postgresql:///stock_analysis')
        if not pg_url.startswith('postgresql'):
            logger.error(f"DATABASE_URL 不是 PostgreSQL 连接: {pg_url}")
            logger.error("请先在 .env 中设置 DATABASE_URL=postgresql:///stock_analysis")
            sys.exit(1)

        logger.info(f"源数据库: sqlite:///test.db (当前 DATABASE_URL)")
        logger.info(f"目标数据库: {pg_url}")

        if DRY_RUN:
            logger.info("=== DRY RUN 模式（只读，不写入）===")

        # 3. 连接 SQLite 读取数据
        sqlite_url = 'sqlite:///instance/test.db'
        sqlite_engine = create_engine(sqlite_url)
        sqlite_conn = sqlite_engine.connect()

        # 4. 连接 PostgreSQL 写入
        pg_engine = create_engine(pg_url)
        pg_conn = pg_engine.connect()

        # 5. 遍历表批量迁移
        total_rows = 0
        for table_name in TABLE_ORDER:
            logger.info(f"--- {table_name} ---")

            # 检查表是否存在
            has_rows = sqlite_conn.execute(
                sql_text(f"SELECT COUNT(*) FROM \"{table_name}\"")
            ).scalar()

            if not has_rows:
                logger.info(f"  → 0 行，跳过")
                continue

            logger.info(f"  源表行数: {has_rows}")

            if DRY_RUN:
                total_rows += has_rows
                continue

            # 分页读取（每次 5000 行）
            offset = 0
            batch_size = 5000
            migrated = 0
            while offset < has_rows:
                rows = sqlite_conn.execute(
                    sql_text(f"SELECT * FROM \"{table_name}\" LIMIT {batch_size} OFFSET {offset}")
                ).fetchall()

                if not rows:
                    break

                columns = list(rows[0]._mapping.keys())
                col_names = ', '.join(f'"{c}"' for c in columns)
                placeholders = ', '.join(f':{c}' for c in columns)

                # 检测 PG 表中哪些字段是 BOOLEAN，需要从 0/1 转换
                pg_col_info = pg_conn.execute(sql_text(f"""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = '{table_name}' AND data_type = 'boolean'
                """)).fetchall()
                bool_cols = {r[0] for r in pg_col_info}

                # 逐行插入（ON CONFLICT DO NOTHING 保证幂等）
                for row in rows:
                    row_dict = dict(row._mapping)
                    # SQLite 存 0/1 但 PG 字段是 BOOLEAN → 转为 True/False
                    for bc in bool_cols:
                        if bc in row_dict and row_dict[bc] is not None:
                            row_dict[bc] = bool(row_dict[bc])
                    try:
                        pg_conn.execute(
                            sql_text(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'),
                            row_dict
                        )
                    except Exception as e:
                        logger.warning(f"  {table_name}: 行跳过（{e}）")

                pg_conn.commit()
                migrated += len(rows)
                offset += batch_size
                logger.info(f"  → {migrated}/{has_rows} 行已迁移")

            total_rows += migrated

        sqlite_conn.close()
        pg_conn.close()

        logger.info(f"=== 迁移完成: 共迁移 {total_rows} 行数据 ===")
        logger.info("下一步：运行 flask db upgrade 更新模型结构")


if __name__ == '__main__':
    main()
