"""426号阶段三：P1-2 三表路由登记数据迁移（daemon 已停止，锁可用）

1. 总库 market_stats_cache / sector_heat_cache 有历史数据（pattern_score_cache
   356号已迁移至 compute_cache.db），将其迁移至 compute_cache.db
2. DROP 总库两张表（迁移后 0 行，ECM _init_tables 自清理同条件会兜底）
3. 验证：三表读写均经 compute_cache.db 分库路由、总库无残留

运行：cd backend && .venv/bin/python scripts/_426_phase3_route_migrate.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.sharding_manager import sharding_manager

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
TOTAL = os.path.join(DUCKDB, 'stock_cache.db')
COMPUTE = os.path.join(DUCKDB, 'compute_cache.db')
TABLES = ['market_stats_cache', 'sector_heat_cache']


def main():
    total = sqlite3.connect(TOTAL, timeout=30)
    compute = sqlite3.connect(COMPUTE, timeout=30)
    try:
        for t in TABLES:
            # 源：总库现有行
            has = total.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", [t]).fetchone()
            rows = []
            if has:
                rows = total.execute(f'SELECT * FROM "{t}"').fetchall()
            print(f"[迁移] {t}: 总库 {len(rows)} 行")

            # 目标表结构（从总库建表 SQL 复制，compute 无表则创建）
            has_c = compute.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", [t]).fetchone()
            if not has_c:
                if has:
                    create_sql = total.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", [t]).fetchone()[0]
                else:
                    raise SystemExit(f"两库均无 {t} 表，无法迁移")
                compute.execute(create_sql)
                print(f"[建表] compute_cache.db {t}")

            # 拷贝
            if rows:
                cols = [r[1] for r in total.execute(f'PRAGMA table_info("{t}")').fetchall()]
                placeholders = ', '.join(['?' for _ in cols])
                col_list = ', '.join(f'"{c}"' for c in cols)
                compute.executemany(
                    f'INSERT OR REPLACE INTO "{t}" ({col_list}) VALUES ({placeholders})', rows)
                compute.commit()
                print(f"[迁移] {t}: 写入 compute_cache.db {len(rows)} 行")

            # DROP 总库表（迁移后 0 行空壳，防止读写分离）
            if has:
                total.execute(f'DROP TABLE IF EXISTS "{t}"')
                total.commit()
                print(f"[DROP] 总库 {t} 已删除")
    finally:
        total.close()
        compute.close()

    # ── 验证 ──
    print("\n[验证]")
    for t in TABLES + ['pattern_score_cache']:
        db = sharding_manager.get_db_for_table(t)
        print(f"  {t} -> 路由 {db}")
        conn = sharding_manager.get_connection(db)
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"  {t} 在 {db} 行数: {n}")
    try:
        total = sqlite3.connect(TOTAL, timeout=30)
        for t in TABLES:
            has = total.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", [t]).fetchone()
            print(f"  总库 {t} 残留: {'有（异常）' if has else '无 ✅'}")
        total.close()
    except Exception as e:
        print(f"  总库验证失败: {e}")


if __name__ == '__main__':
    main()
