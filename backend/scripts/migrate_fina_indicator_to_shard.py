"""B1 修复：将总库 stock_cache.db 的 fina_indicator_cache 全量迁移到财务分库 financial_cache.db

背景：356号分库迁移时 fina_indicator_cache 迁移不完整（分库仅191行，总库22407行），
导致 dim7 估值引擎走分库路由读不到 roe 等财务指标。

安全：按两库交集列 INSERT OR IGNORE 迁移（保留分库已有数据），迁移前已备份。
"""
import os
import sqlite3
import sys

DATA_DIR = "/Users/kalence/Desktop/01-A股股票分析系统/data/duckdb"
STOCK_DB = os.path.join(DATA_DIR, "stock_cache.db")
FIN_DB = os.path.join(DATA_DIR, "financial_cache.db")
TABLE = "fina_indicator_cache"


def get_columns(conn, table):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [c[1] for c in cols]


def migrate():
    src = sqlite3.connect(STOCK_DB)
    dst = sqlite3.connect(FIN_DB)

    src_cols = get_columns(src, TABLE)
    dst_cols = get_columns(dst, TABLE)
    shared = [c for c in src_cols if c in dst_cols]
    print(f"源列({len(src_cols)}): {src_cols}")
    print(f"目标列({len(dst_cols)})")
    print(f"交集列: {shared}")

    if not shared:
        print("无交集列，中止")
        sys.exit(1)

    col_sql = ", ".join(f'"{c}"' for c in shared)
    ph = ", ".join("?" for _ in shared)

    # 源库行数
    src_total = src.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    print(f"源库总行数: {src_total}")

    # 迁移前行数（用于统计新增量）
    dst_before = dst.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    print(f"迁移前目标库行数: {dst_before}")

    # 逐批迁移（避免一次性加载 2.2 万行超内存）
    BATCH = 500
    offset = 0
    while True:
        rows = src.execute(
            f"SELECT {col_sql} FROM {TABLE} ORDER BY ts_code, end_date LIMIT ? OFFSET ?",
            (BATCH, offset),
        ).fetchall()
        if not rows:
            break
        dst.executemany(
            f"INSERT OR IGNORE INTO {TABLE} ({col_sql}) VALUES ({ph})", rows
        )
        dst.commit()
        offset += BATCH
        if offset % 2000 == 0:
            print(f"  ...已处理 {offset} 行")

    dst_after = dst.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    migrated = dst_after - dst_before
    print(f"迁移完成: 目标库 {dst_before} → {dst_after} 行, 新增 {migrated} 行")

    # 验证
    fin_cnt = dst.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    src_cnt = src.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    roe_cnt = dst.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE roe IS NOT NULL"
    ).fetchone()[0]
    print(f"\n验证: financial_cache.fina_indicator_cache 总行数={fin_cnt} (源={src_cnt})")
    print(f"验证: roe 非空计数 = {roe_cnt}")

    src.close()
    dst.close()


if __name__ == "__main__":
    migrate()
