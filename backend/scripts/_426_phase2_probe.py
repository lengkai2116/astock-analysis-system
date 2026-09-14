"""426号阶段二：S2/D4 数据态只读核查（总库空壳 / system_cache / cache_metadata / 路由比对）

运行：cd backend && .venv/bin/python scripts/_426_phase2_probe.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.sharding_manager import sharding_manager

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')


def tables_with_rows(db_name: str) -> dict:
    path = os.path.join(DUCKDB, db_name)
    if not os.path.exists(path):
        return {}
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        out = {}
        for n in names:
            try:
                out[n] = conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            except Exception:
                out[n] = -1
        return out
    finally:
        conn.close()


def main():
    total = tables_with_rows('stock_cache.db')
    print(f"=== stock_cache.db（总库）：{len(total)} 张用户表 ===")
    nonempty = {k: v for k, v in total.items() if v > 0}
    shells = {k: v for k, v in total.items() if v == 0}
    print(f"非空 {len(nonempty)} 张: {nonempty}")
    print(f"0 行空壳 {len(shells)} 张: {sorted(shells.keys())}")

    # 路由判定：空壳表中哪些被路由到分库（可安全 DROP 的候选）
    print("\n=== 空壳表路由判定 ===")
    drop_candidates = []
    for t in sorted(shells.keys()):
        db = sharding_manager.get_db_for_table(t)
        routed = '分库:' + db if db else ('显式总库' if t in sharding_manager._table_to_db else '未登记')
        flag = '✅DROP候选' if db else '⛔保留'
        if db:
            drop_candidates.append(t)
        print(f"  {t}: 路由={routed} {flag}")
    print(f"\nDROP 候选数 = {len(drop_candidates)}")

    # 非空表中有无被路由到分库的（双写异常检查）
    print("\n=== 非空表路由检查（分库路由且总库有数据 = 双写异常）===")
    for t, n in sorted(nonempty.items()):
        db = sharding_manager.get_db_for_table(t)
        if db:
            print(f"  ⚠️ {t}: 总库 {n} 行 但路由到 {db} —— 双写残留，DROP 前须确认")

    print("\n=== system_cache.db ===")
    print(tables_with_rows('system_cache.db'))

    print("\n=== cache_metadata 双份 ===")
    for db in ('stock_cache.db', 'system_cache.db'):
        conn = sqlite3.connect(f'file:{os.path.join(DUCKDB, db)}?mode=ro', uri=True)
        try:
            rows = conn.execute('SELECT COUNT(*) FROM cache_metadata').fetchone()[0]
            sample = conn.execute('SELECT key FROM cache_metadata LIMIT 5').fetchall()
            print(f"  {db}: {rows} 行，样本 {[r[0] for r in sample]}")
        except Exception as e:
            print(f"  {db}: 查询失败 {e}")
        finally:
            conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
