
"""426号阶段四：S5/D3 adj_factor 大表拆分收敛（备份后重建年表）

D3 修复（对应 §10 阶段四 4.2 检验标准）：
1. 备份 history_cache.db → history_cache.db.bak_426_20260912
2. 重建全部 26 张年表 adj_factor_cache_YYYY（2001-2026）：
   - PRIMARY KEY (ts_code, trade_date) + adj_factor REAL（原无主键 + TEXT）
   - GROUP BY 去重重灌（2026 年表 237 万行 → 约 17 万去重键，重复约 14×）
3. 重建全年份 UNION 视图 adj_factor_view（替代原 SELECT * FROM adj_factor_cache_2026）
4. 验证：行数==去重键（零重复）/ typeof(adj_factor)='real' / 具 PK /
   视图覆盖 2001-2026 / 抽查键值口径回归（与备份库一致）
5. 结果落盘 data/alerts/426_p4_adj_factor_report.txt

运行：cd backend && .venv/bin/python scripts/_426_phase4_adj_factor_repair.py
"""
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
DATA_DIR = os.path.dirname(DUCKDB)
HISTORY_DB = os.path.join(DUCKDB, 'history_cache.db')
BACKUP = os.path.join(DUCKDB, 'history_cache.db.bak_426_20260912')
REPORT = os.path.join(DATA_DIR, 'alerts', '426_p4_adj_factor_report.txt')

# 抽查键（口径回归）：2026-08-17 三只 + 2025 年表一只 + 2001 年表一只
# （2001 年表数据自 2001-11-29 起，2001-01-05 无数据属正常，勿选）
SPOT_CHECKS = [
    ('adj_factor_cache_2026', '000001.SZ', '2026-08-17'),
    ('adj_factor_cache_2026', '000002.SZ', '2026-08-17'),
    ('adj_factor_cache_2026', '600000.SH', '2026-08-17'),
    ('adj_factor_cache_2025', '000001.SZ', '2025-06-30'),
    ('adj_factor_cache_2001', '000001.SZ', '2001-11-29'),
]


def main():
    lines = []

    def log(msg):
        print(msg)
        lines.append(msg)

    if not os.path.exists(HISTORY_DB):
        log(f"错误: {HISTORY_DB} 不存在")
        return

    # ── 1. 备份 ──
    if os.path.exists(BACKUP):
        log(f"[备份] 已存在，跳过: {BACKUP}（{os.path.getsize(BACKUP)/1024/1024:.1f} MiB）")
    else:
        shutil.copy2(HISTORY_DB, BACKUP)
        log(f"[备份] {HISTORY_DB} → {BACKUP}（{os.path.getsize(BACKUP)/1024/1024:.1f} MiB）")

    conn = sqlite3.connect(HISTORY_DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    cur = conn.cursor()

    # ── 2. 重建年表 ──
    # 先清理 *_new 残留（上次失败可能遗留），并排除 *_new 误匹配
    for (res) in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'adj_factor_cache_%_new'"):
        cur.execute(f"DROP TABLE IF EXISTS {res[0]}")
        log(f"[清理] 残留临时表: {res[0]}")

    # 视图引用年表，重建期间先 DROP（避免 DROP/RENAME 时视图依赖校验失败）
    cur.execute("DROP VIEW IF EXISTS adj_factor_view")

    year_tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'adj_factor_cache_%' AND name NOT LIKE '%_new' ORDER BY name")]
    if not year_tables:
        log("错误: 未发现年表，退出")
        conn.close()
        return
    log(f"[重建] 共 {len(year_tables)} 张年表")

    for t in year_tables:
        new_t = f"{t}_new"
        cur.execute(f"DROP TABLE IF EXISTS {new_t}")
        cur.execute(f"""
            CREATE TABLE {new_t} (
                ts_code TEXT,
                trade_date TEXT,
                adj_factor REAL,
                cached_at TIMESTAMP,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        old_cnt = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cur.execute(f"""
            INSERT OR REPLACE INTO {new_t} (ts_code, trade_date, adj_factor, cached_at)
            SELECT ts_code, trade_date, CAST(adj_factor AS REAL), MAX(cached_at)
            FROM {t}
            GROUP BY ts_code, trade_date
        """)
        new_cnt = cur.execute(f"SELECT COUNT(*) FROM {new_t}").fetchone()[0]
        cur.execute(f"DROP TABLE {t}")
        cur.execute(f"ALTER TABLE {new_t} RENAME TO {t}")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_date ON {t}(trade_date)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_ts ON {t}(ts_code)")
        if old_cnt != new_cnt:
            log(f"[重建] {t}: {old_cnt:,} → {new_cnt:,} 行（去重 {old_cnt-new_cnt:,}）")
        else:
            log(f"[重建] {t}: {new_cnt:,} 行（无重复）")
    conn.commit()

    # ── 3. 重建全年份视图 ──
    from app.data.create_views import create_adj_factor_view
    ok = create_adj_factor_view(DATA_DIR)
    log(f"[视图] adj_factor_view 重建: {'成功' if ok else '失败'}")

    # ── 4. 验证 ──
    log("\n=== 验证 ===")
    all_ok = True
    for t in year_tables:
        cnt, keys = cur.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT ts_code || '|' || trade_date) FROM {t}").fetchone()
        typ = cur.execute(f"SELECT typeof(adj_factor) FROM {t} LIMIT 1").fetchone()
        pk = [r for r in cur.execute(f"PRAGMA table_info({t})") if r[5]]
        ok_row = (cnt == keys) and (typ and typ[0] == 'real') and len(pk) == 2
        all_ok &= ok_row
        if not ok_row:
            log(f"[FAIL] {t}: 行数={cnt:,} 键={keys:,} typeof={typ} pk={[p[1] for p in pk]}")
    if all_ok:
        log("[OK] 全部 26 张年表：行数==去重键 && typeof='real' && 具 PK(ts_code, trade_date)")
    else:
        log("[FAIL] 存在年表未达标，详见上方 FAIL 行")

    view_sql = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name='adj_factor_view'").fetchone()
    if view_sql:
        year_in_view = [y for y in ('2001', '2005', '2010', '2015', '2020', '2025', '2026')
                        if f'adj_factor_cache_{y}' in view_sql[0]]
        log(f"[视图] adj_factor_view 覆盖年份: {year_in_view}（共 {view_sql[0].count('UNION ALL')+1} 张年表）")
        if len(year_in_view) != 7:
            all_ok = False
            log("[FAIL] 视图未覆盖全部抽查年份")

    # 抽查口径回归：与备份库逐键值对比
    bak = sqlite3.connect(f"file:{BACKUP}?mode=ro", uri=True)
    bak_cur = bak.cursor()
    for t, code, date in SPOT_CHECKS:
        try:
            new_val = cur.execute(
                f"SELECT adj_factor FROM {t} WHERE ts_code=? AND trade_date=?",
                (code, date)).fetchone()
            old_val = bak_cur.execute(
                f"SELECT adj_factor FROM {t} WHERE ts_code=? AND trade_date=?",
                (code, date)).fetchone()
        except Exception as e:
            log(f"[FAIL] 抽查 {t} {code} {date}: {e}")
            all_ok = False
            continue
        if new_val is None or old_val is None:
            log(f"[FAIL] 抽查 {t} {code} {date}: 新={new_val} 旧={old_val}")
            all_ok = False
            continue
        try:
            same = abs(float(new_val[0]) - float(old_val[0])) < 1e-9
        except (TypeError, ValueError):
            same = str(new_val[0]) == str(old_val[0])
        log(f"[抽查] {t} {code} {date}: 新={new_val[0]} 旧={old_val[0]} {'一致' if same else '不一致!'}")
        all_ok &= same
    bak.close()

    log(f"\n结果: {'PASS' if all_ok else 'FAIL'}")
    with open(REPORT, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    log(f"报告已落盘: {REPORT}")
    conn.close()


if __name__ == '__main__':
    main()
