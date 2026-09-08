"""
416号方案：RAW计算配置错误修复 — 主库+分库幂等补列/建表
====================================================
修复项：
- 修复3: indicator_other 补 BBI/ENE/九转列（bbi/ene_upper/ene_lower/nine_buy/nine_sell）
- 修复4: indicator_ma 补 ma120/ma250 列
- 修复5: 主库创建 market_stats_cache 表（若不存在）

主库: data/duckdb/stock_cache.db
分库: data/duckdb/compute_cache.db
幂等: 所有列/表用 PRAGMA table_info / sqlite_master 检查存在性，可重复执行。
"""
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# 项目根目录（脚本位于 backend/scripts/ 下）
ROOT = Path(__file__).resolve().parent.parent.parent

# 目标数据库与补列配置
DB_CONFIG = [
    {
        'path': ROOT / 'data' / 'duckdb' / 'stock_cache.db',
        'name': '主库 stock_cache.db',
        'create_market_stats': True,
        'tables': {
            'indicator_ma': [('ma120', 'REAL'), ('ma250', 'REAL')],
            'indicator_other': [
                ('bbi', 'REAL'), ('ene_upper', 'REAL'), ('ene_lower', 'REAL'),
                ('nine_buy', 'REAL'), ('nine_sell', 'REAL'),
            ],
        },
    },
    {
        'path': ROOT / 'data' / 'duckdb' / 'compute_cache.db',
        'name': '分库 compute_cache.db',
        'create_market_stats': False,
        'tables': {
            'indicator_ma': [('ma120', 'REAL'), ('ma250', 'REAL')],
            'indicator_other': [
                ('bbi', 'REAL'), ('ene_upper', 'REAL'), ('ene_lower', 'REAL'),
                ('nine_buy', 'REAL'), ('nine_sell', 'REAL'),
            ],
        },
    },
]

MARKET_STATS_DDL = """
CREATE TABLE IF NOT EXISTS market_stats_cache (
    stat_date TEXT PRIMARY KEY,
    ma20_ratio REAL, turnover_percentile REAL, limit_ratio REAL,
    rsi_percentile REAL, erp_percentile REAL, margin_trend REAL,
    pe_percentile REAL,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# 表不存在时的兜底建表（与代码 DDL 对齐；已存在表不受影响）
TABLE_DDL = {
    'indicator_ma': """
        CREATE TABLE IF NOT EXISTS indicator_ma (
            ts_code TEXT, trade_date TEXT,
            ma5 REAL, ma10 REAL, ma20 REAL, ma30 REAL, ma60 REAL,
            ma120 REAL, ma250 REAL,
            vol_ma5 REAL, vol_ma10 REAL,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ts_code, trade_date)
        )
    """,
    'indicator_other': """
        CREATE TABLE IF NOT EXISTS indicator_other (
            ts_code TEXT, trade_date TEXT,
            rsi14 REAL,
            kdj_k REAL, kdj_d REAL, kdj_j REAL,
            boll_upper REAL, boll_mid REAL, boll_lower REAL,
            bbi REAL, ene_upper REAL, ene_lower REAL,
            nine_buy REAL, nine_sell REAL,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ts_code, trade_date)
        )
    """,
}


def add_missing_columns(conn: sqlite3.Connection, table: str, columns: list):
    """幂等补列：已存在的列跳过"""
    exist = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, ctype in columns:
        if col not in exist:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
            logger.info(f"  {table} 补列 {col} {ctype}")
        else:
            logger.info(f"  {table} 列 {col} 已存在，跳过")


def migrate():
    for cfg in DB_CONFIG:
        db_path = cfg['path']
        if not db_path.exists():
            logger.warning(f"{cfg['name']} 不存在: {db_path}，跳过")
            continue
        logger.info(f"处理 {cfg['name']}: {db_path}")
        conn = sqlite3.connect(db_path)
        try:
            for table, columns in cfg['tables'].items():
                # 表不存在时先建表（幂等），已存在则保持原结构仅补列
                conn.execute(TABLE_DDL[table])
                add_missing_columns(conn, table, columns)
            # 修复5: 主库创建 market_stats_cache 表
            if cfg.get('create_market_stats'):
                conn.execute(MARKET_STATS_DDL)
                logger.info("  market_stats_cache 表创建/确认完成")
            conn.commit()
        except Exception as e:
            logger.error(f"{cfg['name']} 迁移失败: {e}")
            conn.rollback()
        finally:
            conn.close()
    logger.info("迁移完成")


if __name__ == '__main__':
    migrate()
