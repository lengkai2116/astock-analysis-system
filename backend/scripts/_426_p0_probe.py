"""426号阶段一：只读探测脚本（P0-1 假值 / P0-2 滞后现状核查）

只读：不修改任何数据。运行：cd backend && .venv/bin/python scripts/_426_p0_probe.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.sharding_manager import sharding_manager

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')


def q_shard(table, sql, params=None):
    db = sharding_manager.get_db_for_table(table)
    conn = sharding_manager.get_connection(db)
    return conn.execute(sql, params or []).fetchall()


def main():
    print("=" * 70)
    print("P0-1: market_stats_cache 当前内容（总库 stock_cache.db）")
    conn = sqlite3.connect(os.path.join(DUCKDB, 'stock_cache.db'))
    try:
        rows = conn.execute(
            "SELECT stat_date, ma20_ratio, turnover_percentile, limit_ratio, "
            "rsi_percentile, erp_percentile, margin_trend, pe_percentile, cached_at "
            "FROM market_stats_cache ORDER BY stat_date").fetchall()
        if not rows:
            print("  （空）")
        for r in rows:
            vals = r[1:8]
            constant = len(set(vals)) <= 1 or set(vals) <= {0.1, 0.5, 1.0}
            print(f"  {r[0]}  {list(vals)}  cached_at={r[8]}  {'⚠️疑似假值' if constant else 'OK'}")
    finally:
        conn.close()

    print("=" * 70)
    print("P0-2: indicator_ma / indicator_macd 最新交易日行数对齐")
    for t in ('indicator_ma', 'indicator_macd', 'indicator_other'):
        rows = q_shard(t, f"SELECT MAX(trade_date), COUNT(*) FROM {t} WHERE trade_date=(SELECT MAX(trade_date) FROM {t})")
        r = rows[0]
        print(f"  {t}: 最新={r[0]} 当日行数={r[1]}")
    rows = q_shard('daily_cache', "SELECT MAX(trade_date), COUNT(*) FROM daily_cache")
    print(f"  daily_cache(锚): 最新={rows[0][0]} 当日行数={rows[0][1]}")

    print("=" * 70)
    print("P0-2: [60,249] 根股票 indicator_ma 滞后于 indicator_macd 统计")
    # 每只股票 K 线根数
    bars = dict(q_shard('daily_cache', """
        SELECT ts_code, COUNT(*) FROM daily_cache
        GROUP BY ts_code HAVING COUNT(*) >= 60 AND COUNT(*) < 250"""))
    lag_stocks = []
    if bars:
        placeholders = ','.join('?' * len(bars))
        keys = list(bars.keys())
        ma_latest = dict(q_shard('indicator_ma', f"""
            SELECT ts_code, MAX(trade_date) FROM indicator_ma
            WHERE ts_code IN ({placeholders}) GROUP BY ts_code""", keys))
        macd_latest = dict(q_shard('indicator_macd', f"""
            SELECT ts_code, MAX(trade_date) FROM indicator_macd
            WHERE ts_code IN ({placeholders}) GROUP BY ts_code""", keys))
        for code, _nb in sorted(bars.items()):
            ml = ma_latest.get(code)
            mcl = macd_latest.get(code)
            if ml != mcl:
                lag_stocks.append((code, bars[code], ml, mcl))
    print(f"  [60,249] 区间股票数={len(bars)}，其中 MA 滞后 MACD 的股票数={len(lag_stocks)}")
    for code, nb, ml, mcl in lag_stocks[:20]:
        print(f"    {code} 根数={nb} ma最新={ml} macd最新={mcl}")
    if len(lag_stocks) > 20:
        print(f"    ... 共 {len(lag_stocks)} 只")
    return 0


if __name__ == '__main__':
    sys.exit(main())
