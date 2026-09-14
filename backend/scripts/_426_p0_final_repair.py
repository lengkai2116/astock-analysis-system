"""426号阶段一：P0-1 数据修复最终执行（daemon 已停止，锁可用）

1. 清除 market_stats_cache 已入库假值行（精确匹配兜底常量模式）
2. 用修复后 _precompute_market_stats 回填 09-07~09-11 真实统计
3. 全量验证：market_stats 非常量 / ma-macd 对齐 / QualityChecker 整日校验
4. 结果落盘到 data/alerts/426_p0_verify_report.txt 供归档

运行：cd backend && .venv/bin/python scripts/_426_p0_final_repair.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_daemon as dd
from app.data.enhanced_cache_manager import get_ecm_instance
from app.data.sharding_manager import sharding_manager
from app.data.stg_quality import QualityChecker

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
STAT_DATES = ['2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11']
REPORT = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'alerts', '426_p0_verify_report.txt')

FAKE_WHERE = ("ma20_ratio=0.5 AND turnover_percentile=0.5 AND limit_ratio=0.1 "
              "AND rsi_percentile=0.5 AND erp_percentile=0.5 AND margin_trend=0.5 "
              "AND pe_percentile=0.5")


def q_shard(table, sql, params=None):
    db = sharding_manager.get_db_for_table(table)
    conn = sharding_manager.get_connection(db)
    return conn.execute(sql, params or []).fetchall()


def main():
    lines = []
    def log(msg):
        print(msg)
        lines.append(msg)

    # ── 1. 清除假值行（先于 ECM 创建：ECM _init_tables 的 DDL/盲 ALTER 会在
    #      主连接遗留未提交事务，阻塞同一进程的其他连接写总库——与 daemon 侧
    #      锁同根因；daemon 已停，此处用独立连接先行清理）──
    conn = sqlite3.connect(os.path.join(DUCKDB, 'stock_cache.db'), timeout=30)
    try:
        fake = conn.execute(f"SELECT COUNT(*) FROM market_stats_cache WHERE {FAKE_WHERE}").fetchone()[0]
        if fake:
            conn.execute(f"DELETE FROM market_stats_cache WHERE {FAKE_WHERE}")
            conn.commit()
            log(f"[P0-1] 已清除假值行: {fake} 行")
        else:
            log("[P0-1] 无假值行需清除")
    finally:
        conn.close()

    # ── 2. 建立 ECM（rollback 清除 _init_tables 遗留事务，避免自锁）──
    ecm = get_ecm_instance()
    try:
        ecm.conn.rollback()
    except Exception:
        pass

    # ── 3. 回填真实统计 ──
    for d in STAT_DATES:
        dd._precompute_market_stats(target_date=d)
    log("[P0-1] 回填完成，market_stats_cache 当前内容:")
    conn = sqlite3.connect(os.path.join(DUCKDB, 'stock_cache.db'), timeout=30)
    try:
        rows = conn.execute(
            "SELECT stat_date, ma20_ratio, turnover_percentile, limit_ratio, "
            "rsi_percentile, erp_percentile, margin_trend, pe_percentile "
            "FROM market_stats_cache ORDER BY stat_date").fetchall()
        non_const = 0
        for r in rows:
            vals = [round(float(v), 4) if v is not None else None for v in r[1:8]]
            flag = '⚠️疑似假值' if (len(set(vals)) <= 1 or set(vals) <= {0.1, 0.5, 1.0}) else 'OK'
            if flag == 'OK':
                non_const += 1
            log(f"    {r[0]}  {vals}  {flag}")
        log(f"[P0-1 验收] 非常量行数={non_const}/{len(rows)}（§7验收1：近 5 交易日均非常量兜底值）")
    finally:
        conn.close()

    # ── 3. ma/macd 对齐验证（P0-2 已于前序执行，此处复核）──
    latest = q_shard('indicator_macd', "SELECT MAX(trade_date) FROM indicator_macd")[0][0]
    ma_n = q_shard('indicator_ma', "SELECT COUNT(*) FROM indicator_ma WHERE trade_date=?", [latest])[0][0]
    macd_n = q_shard('indicator_macd', "SELECT COUNT(*) FROM indicator_macd WHERE trade_date=?", [latest])[0][0]
    daily_n = q_shard('daily_cache', "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [latest])[0][0]
    dev = abs(ma_n - macd_n) / macd_n if macd_n else 1.0
    log(f"[P0-2 验收] {latest}: indicator_ma={ma_n} indicator_macd={macd_n} daily_cache={daily_n}")
    log(f"[P0-2 验收] ma/macd 偏差={dev:.2%}（§7验收2 标准 ≤0.1%）{'✅' if dev <= 0.001 else '❌'}")

    # ── 4. QA 整日校验（只读）──
    checker = QualityChecker(ecm)
    results = checker.check_pipeline_date(str(latest))
    failed = [r for r in results if not r.passed]
    log(f"[QA] {latest} 整日校验: 失败 {len(failed)}/{len(results)}")
    for r in failed[:12]:
        log(f"    FAIL {r.table} [{r.kind}] expected={r.expected} actual={r.actual}")
        for i in r.issues[:2]:
            log(f"        - {i}")
    if not failed:
        log("[QA] ✅ 全部通过（含 market_stats_cache 常量守卫 + indicator_ma 0.99 + ma/macd 对齐）")

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    log(f"[报告] 已写入 {REPORT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
