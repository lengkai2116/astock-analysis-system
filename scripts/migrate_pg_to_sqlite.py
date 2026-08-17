#!/usr/bin/env python3
"""331号方案 Step2：PG → SQLite 业务数据迁移（一次性脚本）

迁移两张有数据的表：
- strategy_templates_v2（PG 20 条 → SQLite 并集去重）
- signal_records（PG 11 条 → SQLite 追加合并）

用法: backend/.venv/bin/python scripts/migrate_pg_to_sqlite.py
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

PG_DSN = os.getenv('PG_DSN', 'dbname=stock_analysis')
SQLITE_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'data', 'app.db')

# strategy_templates_v2 列清单（与 SQLite schema 对齐）
TEMPLATE_COLS = ['id', 'name', 'description', 'template_type', 'code_template',
                 'parameters', 'output_schema', 'is_system', 'is_active', 'author',
                 'version', 'usage_count', 'created_at', 'updated_at', 'cat',
                 'catLabel', 'catCN', 'icon', 'nameCN', 'tags', 'ready', 'vibe']

# signal_records 列清单（与 SQLite schema 对齐）
SIGNAL_COLS = ['id', 'ts_code', 'signal_date', 'strategy_name', 'signal_type',
               'confidence', 'entry_price', 'risk_line', 'target_price',
               'entry_zone_low', 'entry_zone_high', 'price_t5', 'price_t10',
               'price_t20', 'return_t5', 'return_t10', 'return_t20',
               'hit_target_t5', 'hit_target_t10', 'hit_target_t20',
               'hit_stop_t5', 'hit_stop_t10', 'hit_stop_t20', 'max_drawdown_t20',
               'verification_status', 'is_win_5d', 'is_win_10d', 'is_win_20d',
               'signal_snapshot', 'created_at', 'updated_at']


def _connect_pg():
    import psycopg2
    return psycopg2.connect(PG_DSN)


def _json_dumps(v):
    import json
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def migrate_table(pg_conn, sq_conn, table, cols, pk='id'):
    """读 PG 表 → 写入 SQLite（INSERT OR IGNORE 按主键去重）"""
    col_list = ', '.join(cols)
    pg_cur = pg_conn.cursor()
    pg_cur.execute(f"SELECT {col_list} FROM {table} ORDER BY {pk}")
    pg_rows = pg_cur.fetchall()
    if not pg_rows:
        print(f"[{table}] PG 无数据，跳过")
        return 0

    sq_cols = sq_conn.execute(f"PRAGMA table_info({table})").fetchall()
    sq_col_names = [c[1] for c in sq_cols]
    # 仅取 SQLite 存在的列
    valid_cols = [c for c in cols if c in sq_col_names]
    valid_idx = [cols.index(c) for c in valid_cols]

    placeholders = ', '.join('?' * len(valid_cols))
    sql = (f"INSERT OR IGNORE INTO {table} ({', '.join(valid_cols)}) "
           f"VALUES ({placeholders})")
    inserted = 0
    skipped = 0
    for row in pg_rows:
        vals = [_json_dumps(row[i]) for i in valid_idx]
        cur = sq_conn.execute(sql, vals)
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    sq_conn.commit()
    print(f"[{table}] PG {len(pg_rows)} 条 → 插入 {inserted} 条, 去重跳过 {skipped} 条")
    return inserted


def main():
    # 备份 SQLite
    bak = f"{SQLITE_DB}.bak.331"
    shutil.copy2(SQLITE_DB, bak)
    print(f"SQLite 已备份: {bak}")

    sq_conn = sqlite3.connect(SQLITE_DB)
    pg_conn = _connect_pg()
    print(f"PG 连接成功: {PG_DSN}")

    migrate_table(pg_conn, sq_conn, 'strategy_templates_v2', TEMPLATE_COLS)
    migrate_table(pg_conn, sq_conn, 'signal_records', SIGNAL_COLS)

    # 校验
    for t in ('strategy_templates_v2', 'signal_records'):
        n = sq_conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"校验: {t} 最终行数 = {n}")

    sq_conn.close()
    pg_conn.close()
    print("迁移完成")


if __name__ == '__main__':
    main()
