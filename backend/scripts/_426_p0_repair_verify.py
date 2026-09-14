"""426号阶段一：P0-2 MA 追平补算 + P0-1 功能性验证（总库写锁阻塞下）

P0-2（写 compute_cache.db，锁可用）：对 [60,249] 滞后股票补算 indicator_ma。
P0-1（不写总库）：调用修复后 _precompute_market_stats 读分库计算，验证内存态
  7 项统计为真实非常量值，并与分库直算 ma20_ratio 口径比对（总库被 daemon
  遗留写事务锁定时，持久化步骤自动告警跳过，不影响功能验证）。

运行：cd backend && .venv/bin/python scripts/_426_p0_repair_verify.py --catchup
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_daemon as dd
from app.data.enhanced_cache_manager import get_ecm_instance
from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
from app.data.sharding_manager import sharding_manager

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
TARGET = '2026-09-11'


def q_shard(table, sql, params=None):
    db = sharding_manager.get_db_for_table(table)
    conn = sharding_manager.get_connection(db)
    return conn.execute(sql, params or []).fetchall()


def main():
    ecm = get_ecm_instance()

    # ── P0-2：滞后股票 MA 追平 ──
    bars = dict(q_shard('daily_cache', """
        SELECT ts_code, COUNT(*) FROM daily_cache
        GROUP BY ts_code HAVING COUNT(*) >= 60 AND COUNT(*) < 250"""))
    keys = list(bars.keys())
    ph = ','.join('?' * len(keys))
    ma_latest = dict(q_shard('indicator_ma',
                             f"SELECT ts_code, MAX(trade_date) FROM indicator_ma WHERE ts_code IN ({ph}) GROUP BY ts_code",
                             keys))
    macd_latest = dict(q_shard('indicator_macd',
                               f"SELECT ts_code, MAX(trade_date) FROM indicator_macd WHERE ts_code IN ({ph}) GROUP BY ts_code",
                               keys))
    lag = [c for c in keys if ma_latest.get(c) != macd_latest.get(c)]
    print(f"[P0-2] 滞后股票 {len(lag)} 支，开始补算（写 compute_cache.db）...")
    mgr = PrecomputeIndicatorManager(ecm)
    ok = 0
    for code in lag:
        try:
            df = ecm.get_cached_daily(code)
            if df is not None and len(df) >= 60:
                mgr.precompute_all_indicators(code, df)
                ok += 1
        except Exception as e:
            print(f"    {code} 补算失败: {e}")
    print(f"[P0-2] 补算完成: {ok}/{len(lag)}")

    # 追平验证
    ma_latest2 = dict(q_shard('indicator_ma',
                              f"SELECT ts_code, MAX(trade_date) FROM indicator_ma WHERE ts_code IN ({ph}) GROUP BY ts_code",
                              keys))
    still_lag = [c for c in keys if ma_latest2.get(c) != macd_latest.get(c)]
    ma_n = q_shard('indicator_ma', "SELECT COUNT(*) FROM indicator_ma WHERE trade_date=?", [TARGET])[0][0]
    macd_n = q_shard('indicator_macd', "SELECT COUNT(*) FROM indicator_macd WHERE trade_date=?", [TARGET])[0][0]
    daily_n = q_shard('daily_cache', "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [TARGET])[0][0]
    print(f"[验证] {TARGET}: indicator_ma={ma_n} indicator_macd={macd_n} daily_cache={daily_n}")
    print(f"[验证] 仍滞后股票数={len(still_lag)}（标准=0）；ma/macd 偏差={abs(ma_n-macd_n)/macd_n:.2%}（标准 ≤0.1%）")

    # ── P0-1：修复后函数功能性验证（内存态，不依赖总库写入）──
    print("[P0-1] 调用修复后 _precompute_market_stats(target_date='2026-09-11')（内存态验证）:")
    dd._precompute_market_stats(target_date=TARGET)
    stats = dict(dd._market_stats_cache)
    vals = [stats.get(k) for k in ('ma20_ratio', 'turnover_percentile', 'limit_ratio',
                                   'rsi_percentile', 'erp_percentile', 'margin_trend', 'pe_percentile')]
    print(f"    计算值: {[round(float(v), 4) if v is not None else None for v in vals]}")
    non_const = len(set(vals)) > 1 and not set(vals) <= {0.1, 0.5, 1.0}
    print(f"    非常量判定: {'✅ 真实值' if non_const else '❌ 仍为常量'}")

    # 独立口径复核：分库直算 ma20_ratio（收盘>MA20 占比）
    rows = q_shard('daily_cache', """
        SELECT COUNT(*) as total, SUM(CASE WHEN close > SMA_20 THEN 1 ELSE 0 END) as above
        FROM (
            SELECT ts_code, trade_date, close,
                   AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as SMA_20
            FROM daily_cache WHERE trade_date = ?
        )""", [TARGET])
    direct = (rows[0][1] or 0) / rows[0][0] if rows and rows[0][0] else None
    fn_val = float(stats['ma20_ratio']) if stats.get('ma20_ratio') is not None else None
    match = fn_val is not None and direct is not None and abs(fn_val - direct) < 1e-9
    print(f"    ma20_ratio: 函数={fn_val}  分库直算={round(direct, 6) if direct is not None else None}  一致={match}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
