"""426号阶段二：S2/D4 数据整改执行（daemon 已停止，锁可用）

1. 备份 stock_cache.db / system_cache.db（.bak_426_20260912，阶段五 S6 可回收）
2. DROP 29 张"路由到分库且总库副本 0 行"的空壳表（与 _init_tables 自清理同条件，
   显式执行保证一次性清理；之后 ECM 启动自清理维持不复活）
3. DROP system_cache.db 的 cache_metadata（归一：总库 30 行为权威）
4. 验证：表数/空壳清零/cache_metadata 单处/list_unmapped_tables

运行：cd backend && .venv/bin/python scripts/_426_phase2_repair.py
"""
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.sharding_manager import sharding_manager

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
STAMP = '426_20260912'


def main():
    total_path = os.path.join(DUCKDB, 'stock_cache.db')
    system_path = os.path.join(DUCKDB, 'system_cache.db')

    # ── 1. 备份 ──
    for p in (total_path, system_path):
        bak = f'{p}.bak_{STAMP}'
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
            print(f"[备份] {os.path.basename(p)} → {os.path.basename(bak)}")
        else:
            print(f"[备份] 已存在，跳过: {os.path.basename(bak)}")

    # ── 2. DROP 29 张空壳（路由到分库且 0 行）──
    conn = sqlite3.connect(total_path, timeout=30)
    try:
        shells = []
        for (t,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if sharding_manager.get_db_for_table(t) and conn.execute(
                    f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0:
                shells.append(t)
        print(f"[DROP] 待清理空壳 {len(shells)} 张: {sorted(shells)}")
        for t in shells:
            conn.execute(f'DROP TABLE IF EXISTS "{t}"')
        conn.commit()
        print(f"[DROP] 完成，共 {len(shells)} 张")

        # ── 3. system_cache.db cache_metadata 归一 ──
        sys_conn = sqlite3.connect(system_path, timeout=30)
        try:
            has = sys_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cache_metadata'").fetchone()
            if has:
                rows = sys_conn.execute('SELECT COUNT(*) FROM cache_metadata').fetchone()[0]
                sys_conn.execute('DROP TABLE cache_metadata')
                sys_conn.commit()
                print(f"[归一] system_cache.db cache_metadata 已 DROP（原 {rows} 行陈旧副本）")
            else:
                print("[归一] system_cache.db 无 cache_metadata")
        finally:
            sys_conn.close()

        # ── 4. 验证 ──
        total_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        nonempty = [(t,) for (t,) in total_tables
                    if conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] > 0]
        print(f"[验证] 总库表数: {len(total_tables)}（非空 {len(nonempty)}，含空壳 {len(total_tables) - len(nonempty)}）")
        print(f"[验证] 非空表: {sorted(t for (t,) in nonempty)}")
        cm = conn.execute('SELECT COUNT(*) FROM cache_metadata').fetchone()[0]
        print(f"[验证] 总库 cache_metadata: {cm} 行（权威副本）")
    finally:
        conn.close()

    # ── 5. list_unmapped_tables（新 API 扫描）──
    sm = sharding_manager
    total_conn = sqlite3.connect(total_path, timeout=30)
    try:
        unmapped = sm.list_unmapped_tables(total_conn=total_conn)
        print(f"[自检] 未登记分库路由的表清单: {unmapped}")
    finally:
        total_conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
