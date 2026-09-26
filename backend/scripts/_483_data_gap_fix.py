"""483号 采集层实施与核对脚本（口径层核对 + ③ margin 回补 + ② 60min 聚合）

用法（必须用 backend/.venv/bin/python，且确认无 data_daemon 进程）：
    .venv/bin/python scripts/_483_data_gap_fix.py check            # 只读核对现状
    .venv/bin/python scripts/_483_data_gap_fix.py backfill-margin  # ③ 补采最新日 margin
    .venv/bin/python scripts/_483_data_gap_fix.py aggregate-60min  # ② 全市场 1min→60min 聚合
"""
import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('483')


def _sm():
    from app.data.sharding_manager import sharding_manager
    return sharding_manager


def _scalar(table, sql, params=None):
    sm = _sm()
    conn = sm.get_connection(sm.get_db_for_table(table))
    row = conn.execute(sql, params or []).fetchone()
    return row[0] if row else None


def _rows(table, sql, params=None):
    sm = _sm()
    conn = sm.get_connection(sm.get_db_for_table(table))
    return conn.execute(sql, params or []).fetchall()


def check():
    from app.data.market_universe import stock_only_sql
    pred, params = stock_only_sql()
    d = _scalar('daily_cache', "SELECT MAX(trade_date) FROM daily_cache")
    all_n = _scalar('daily_cache', "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [d])
    stock_n = _scalar('daily_cache',
                      f"SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND {pred}", [d] + params)
    print(f"== 口径层（A1）日期 {d} ==")
    print(f"  daily_cache 全部={all_n}  个股={stock_n}  剔除指数={all_n - stock_n}")

    # QA 判定（真实 QualityChecker）
    from app.data.stg_quality import QualityChecker
    qc = QualityChecker()
    print(f"  QA daily_base(个股)={qc.daily_base(d)}")
    for t in ['indicator_ma', 'margin_cache']:
        r = qc.check_table(t, d)
        print(f"  QA {t}: passed={r.passed} actual={r.actual} expected={r.expected} issues={r.issues}")

    print(f"\n== ③ margin 每日覆盖（近 6 日）==")
    for td, c in _rows('margin_cache',
                       "SELECT trade_date, COUNT(DISTINCT ts_code) FROM margin_cache "
                       "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 6"):
        print(f"  {td}: {c}")
    base = _scalar('margin_cache',
                   "SELECT MAX(c) FROM (SELECT COUNT(DISTINCT ts_code) c FROM margin_cache "
                   "WHERE trade_date<? GROUP BY trade_date ORDER BY trade_date DESC LIMIT 20)", [d])
    print(f"  自基准(近20日峰值)={base}")

    print(f"\n== ② minute_kline_cache freq 分布 ==")
    for freq, codes, n in _rows('minute_kline_cache',
                                "SELECT freq, COUNT(DISTINCT ts_code), COUNT(*) "
                                "FROM minute_kline_cache GROUP BY freq ORDER BY freq"):
        print(f"  {freq}: {codes} 只 / {n} 行")


def backfill_margin():
    import data_daemon as dd
    if dd._ecm is None:  # 独立运行需先初始化 ECM 全局（daemon 主循环才会设）
        from app.data.enhanced_cache_manager import get_ecm_instance
        dd._ecm = get_ecm_instance()
    d = _scalar('margin_cache', "SELECT MAX(trade_date) FROM margin_cache")
    d_fmt = str(d).replace('-', '')
    print(f"补采 margin {d}（{d_fmt}）...")
    added = dd._batch_margin(d_fmt)
    after = _scalar('margin_cache',
                    "SELECT COUNT(DISTINCT ts_code) FROM margin_cache WHERE trade_date=?", [d])
    print(f"  → 写入 {added} 条；该日最新覆盖 {after}")


def aggregate_60min():
    from app.data.minute_backfill import aggregate_1min_to_60min
    d = _scalar('minute_kline_cache', "SELECT MAX(trade_date) FROM minute_kline_cache WHERE freq='1min'")
    codes = [r[0] for r in _rows('minute_kline_cache',
             "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE freq='1min' AND trade_date=?", [d])]
    print(f"1min 最新日 {d}：{len(codes)} 只，开始 1min→60min 本地聚合...")
    n = aggregate_1min_to_60min(codes)
    print(f"  → 聚合完成 {n}/{len(codes)} 只")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    {'check': check, 'backfill-margin': backfill_margin, 'aggregate-60min': aggregate_60min}[cmd]()
